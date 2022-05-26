#!/usr/bin/env python
#
# History:
#  2014-Dec-07  DG
#    Changed to check for either /data1 or /dppdata1, so that the
#    routine will work on either dpp or pipeline.  Also now writes
#    output files to shared file location /common/tmp/txt/.  Also,
#    moved argv parsing to main, so that dump_tsys() is called
#    with arguments for normal usage
#  2014-Dec-13  DG
#    Added rd_fdb() routine to read the contents of an FDB file,
#    which is a finder file to identify scan types and files belonging
#    to a scan.  This could be used to dump all files for a scan, using
#    only the start time of the scan.
#  2015-May-23  DG
#    Split task of finding files into a separate routine, file_list(),
#    so that it can be reused.  Added a more direct way of reading data
#    from Miriad files, using aipy, in new routine rd_miriad_tsys().
#  2015-May-29  DG
#    Converted from using datime() to using Time() based on astropy.
#  2015-Jun-27  DG
#    Changed the code to standardize on names, content, and order of indices
#    of outputs for rd_miriad_tsys.  Names ut_mjd, fghz, and tsys will be used,
#    with units hopefully made obvious.  Order of indices will be
#          (nant/nbl, npol, nfreq, ntimes).
#  2015-Jun-28  DG
#    Added common_val_idx() from solpnt, so that I do not have to include
#    the entire solpnt just for this!
#  2016-Apr-04  DG
#    Changed to work with tawa and pipeline data in /data1/eovsa... dir
#  2016-May-05  DG
#    Add rd_miriad_tsys_16() routine to read 16-ant correlator data.
#  2016-May-10  DG
#    Fix bug that could not find older data that has been moved to pipeline
#  2017-May-13  BC
#    Added rd_ufdb() routine to read the contents of an UFDB file. This is similar
#    to rd_fdb() but instead works to find UDB files.
#  2017-May-17  DG
#    Added auto keyword to rd_miriad_tsys_16(), which returns the real
#    part of the autocorrelation instead of total power, in the tsys key.
#  2017-Sep-05  DG
#    Added call to apply_gain_corr() in rd_miriad_tsys_16(), to correct for
#    attenuation settings.
#  2018-Jan-04  DG
#    Added tref parameter to rd_miriad_tsys_16() call, so that reference
#    time of attenuation correction can pertain to the data time (used
#    for SOLPNTCAL).
#  2018-Jan-26  DG
#    Changed to call gc.apply_fem_level() instead of gc.apply_gain_corr(), since
#    this uses frequency-dependent attenuations.
#  2019-May-21  DG
#    Added skycal keyword to rd_miriad_tsys_16()
#  2021-Jul-20  DG
#    Added rd_ifdb() to read IFDB files, which is attempted by rd_fdb() initially
#    and if it fails then the corresponding FDB file is attempted to be read.

import subprocess, time, sys, glob
import numpy as np
from .util import Time


def common_val_idx(array1, array2):
    ''' Find the common values in two sorted arrays, and return the array
        of indexes of those common values in the two arrays.
    '''
    common = np.intersect1d(array1, array2, True)
    idx1 = np.searchsorted(array1, common)
    idx2 = np.searchsorted(array2, common)
    return idx1, idx2


def file_list(trange, udb=False):
    ''' Find IDB files between the dates/times provided in trange.
        Input is a 2-element Time() object with start time trange[0] and end time trange[1]
        Returns files as a list, if found, or an empty list ([]) if not found.
    '''
    # Find files corresponding to date of first time
    fstr = trange[0].iso
    if udb:
        # Check for existence of /data1/UDB:
        folder = '/data1/UDB/' + str(int(trange[0].jyear))
        files = glob.glob(folder + '/UDB' + fstr.replace('-', '').split()[0] + '*')
        files.sort()
        # Check if second time has different date
        mjd1, mjd2 = trange.mjd.astype('int')
        if mjd2 != mjd1:
            if (mjd2 - 1) != mjd1:
                usage('Second date must differ from first by at most 1 day')
            else:
                fstr2 = trange[1].iso
                files2 = glob.glob(folder + '/UDB' + fstr2.replace('-', '').split()[0] + '*')
                files2.sort()
                files += files2
    else:
        # Check for existence of /data1/IDB, or use /dppdata1/IDB if not found:
        folder = '/data1/IDB'
        if glob.glob(folder) == []:
            folder = '/dppdata1/IDB'
            files = glob.glob(folder + '/IDB' + fstr.replace('-', '').split()[0] + '*')
            files.sort()
        if files == [] or glob.glob(folder) == []:
            datdir = trange[0].iso[:10].replace('-', '')
            folder = '/common/archive/data1/eovsa/fits/IDB/' + datdir
            files = glob.glob(folder + '/IDB' + fstr.replace('-', '').split()[0] + '*')
            files.sort()
        # Check if second time has different date
        mjd1, mjd2 = trange.mjd.astype('int')
        if mjd2 != mjd1:
            if (mjd2 - 1) != mjd1:
                usage('Second date must differ from first by at most 1 day')
            else:
                if folder[:22] == '/common/archive/data1/eovsa/fits/IDB/':
                    datdir = trange[1].iso[:10].replace('-', '')
                    folder = '/common/archive/data1/eovsa/fits/IDB/' + datdir
                fstr2 = trange[1].iso
                files2 = glob.glob(folder + '/IDB' + fstr2.replace('-', '').split()[0] + '*')
                files2.sort()
                files += files2

    def fname2mjd(filename):
        fstem = filename.split('/')[-1]
        fstr = fstem[3:7] + '-' + fstem[7:9] + '-' + fstem[9:11] + ' ' + fstem[11:13] + ':' + fstem[
                                                                                              13:15] + ':' + fstem[
                                                                                                             15:17]
        t = Time(fstr)
        return t.mjd

    filelist = []
    for filename in files:
        mjd = fname2mjd(filename)
        if mjd >= trange[0].mjd and mjd < trange[1].mjd:
            filelist.append(filename)
    return filelist


def dump_tsys(trange):
    ''' Routine to dump tsys data for a given timerange using Miriad's varplt.
        Input is a 2-element Time() object with start time trange[0] and end time trange[1]
    '''
    # Find files corresponding to times
    filelist = file_list(trange)

    if filelist == []:
        print('No files find between', trange[0].iso, 'and', trange[1].iso)
        return

    for filename in filelist:
        print('Processing', filename)
        vis = 'vis=' + filename
        log = 'log=/common/tmp/txt/xt' + filename.split('IDB')[-1] + '.txt'
        xaxis = 'xaxis=time'
        yaxis = 'yaxis=xtsys'
        res = subprocess.Popen(['varplt', vis, xaxis, yaxis, log], stdout=subprocess.PIPE)
        log = 'log=/common/tmp/txt/yt' + filename.split('IDB')[-1] + '.txt'
        yaxis = 'yaxis=ytsys'
        res = subprocess.Popen(['varplt', vis, xaxis, yaxis, log], stdout=subprocess.PIPE)


def rd_miriad_tsys(trange, udb=False):
    ''' Read total power data (TSYS) directly from Miriad files for time range
        given by d1, d2.
        
        Major change to standardize output to ut_mdj, fghz, and order
        of indices of tsys as (npol, nant, nf, ntimes)
    '''
    import aipy

    # Find files corresponding to times
    filelist = file_list(trange, udb=udb)
    if filelist == []:
        print('No files find between', trange[0].iso, 'and', trange[1].iso)
        return None
    # Open first file and check that it has correct form
    uv = aipy.miriad.UV(filelist[0])
    uvok = True
    if 'source' in uv.vartable:
        src = uv['source']
    else:
        uvok = False
    if 'sfreq' in uv.vartable:
        fghz = uv['sfreq']
    else:
        uvok = False
    if 'nants' in uv.vartable:
        nants = uv['nants']
    else:
        uvok = False
    if 'ut' in uv.vartable:
        pass
    else:
        uvok = False
    if 'xtsys' in uv.vartable:
        pass
    else:
        uvok = False
    if 'ytsys' in uv.vartable:
        pass
    else:
        uvok = False
    if not uvok:
        print('Miriad file has bad format')
        return None

    utd = []
    xtsys = []
    ytsys = []
    # Loop over filenames
    for filename in filelist:
        uv = aipy.miriad.UV(filename)
        if uv['source'] != src:
            print('Source name:', uv['source'], 'is different from initial source name:', src)
            print('Will stop reading files.')
            break
        # uv.select('antennae',0,1,include=True)
        # Read first record of data
        preamble, data = uv.read()
        ut = preamble[1]
        utd.append(ut - 2400000.5)
        xtsys.append(uv['xtsys'])
        ytsys.append(uv['ytsys'])
        for preamble, data in uv.all():
            # Look for time change
            if preamble[1] != ut:
                # Time has changed, so read new xtsys and ytsys
                ut = preamble[1]
                xtsys.append(uv['xtsys'])
                ytsys.append(uv['ytsys'])
                utd.append(ut - 2400000.5)
    utd = np.array(utd)
    xtsys = np.array(xtsys)
    xtsys.shape = (len(utd), len(fghz), nants)
    ytsys = np.array(ytsys)
    ytsys.shape = (len(utd), len(fghz), nants)
    tsys = np.array((xtsys, ytsys))
    tsys = np.swapaxes(tsys, 1, 3)  # Order is now npol, nants, nf, nt
    tsys = np.swapaxes(tsys, 0, 1)  # Order is now nants, npol, nf, nt, as desired
    good, = np.where(tsys.sum(0).sum(0).sum(1) != 0.0)
    tsys = tsys[:, :, good, :]
    fghz = fghz[good]
    return {'source': src, 'fghz': fghz, 'ut_mjd': utd, 'tsys': tsys}


def rd_miriad_tsys_16(trange, udb=False, auto=False, tref=None, skycal=None, desat=False):
    ''' Read total power data (TSYS) directly from Miriad files for time range
        given by trange.  This version works only for 16-ant correlator
        Simply calls read_idb and returns a subset of the data with new dictionary keys.
        
        2018-01-26  Changed to call gc.apply_fem_level() instead of gc.apply_gain_corr().
        2019-05-21  Added skycal keyword, simply for passing through to apply_fem_level().
    '''
    from . import gaincal2 as gc
    from . import read_idb
    from . import calibration as cal
    out = read_idb.read_idb(trange, desat=desat)
    #cout = gc.apply_gain_corr(out, tref=tref)
    try:
        cout = gc.apply_fem_level(out, skycal=skycal)
    except:
        print('RD_MIRIAD_TSYS_16: Error applying FEM level correction. No correction applied')
        cout = out
    if auto:
        return {'source':out['source'], 'fghz':out['fghz'], 'ut_mjd':out['time']-2400000.5, 'tsys':np.real(cout['a'][:,:2])}
    else:
        return {'source':out['source'], 'fghz':out['fghz'], 'ut_mjd':out['time']-2400000.5, 'tsys':cout['p']}

def rd_miriad_tsamp(trange, udb=False):
    ''' Read total power data (TSYS) directly from Miriad files for time range
        given by d1, d2.
        
        Major change to standardize output to ut_mdj, fghz, and order
        of indices of tsys as (npol, nant, nf, ntimes)
    '''
    import aipy

    # Find files corresponding to times
    filelist = file_list(trange, udb=udb)
    if filelist == []:
        print('No files find between', trange[0].iso, 'and', trange[1].iso)
        return None
    # Open first file and check that it has correct form
    uv = aipy.miriad.UV(filelist[0])
    uvok = True
    if 'source' in uv.vartable:
        src = uv['source']
    else:
        uvok = False
    if 'sfreq' in uv.vartable:
        fghz = uv['sfreq']
    else:
        uvok = False
    if 'nants' in uv.vartable:
        nants = uv['nants']
    else:
        uvok = False
    if 'ut' in uv.vartable:
        pass
    else:
        uvok = False
    if 'xsampler' in uv.vartable:
        pass
    else:
        uvok = False
    if 'ysampler' in uv.vartable:
        pass
    else:
        uvok = False
    if not uvok:
        print('Miriad file has bad format')
        return None

    utd = []
    xtsys = []
    ytsys = []
    # Loop over filenames
    for filename in filelist:
        uv = aipy.miriad.UV(filename)
        if uv['source'] != src:
            print('Source name:', uv['source'], 'is different from initial source name:', src)
            print('Will stop reading files.')
            break
        # uv.select('antennae',0,1,include=True)
        # Read first record of data
        preamble, data = uv.read()
        ut = preamble[1]
        utd.append(ut - 2400000.5)
        xtsys.append(uv['xsampler'])
        ytsys.append(uv['ysampler'])
        for preamble, data in uv.all():
            # Look for time change
            if preamble[1] != ut:
                # Time has changed, so read new xtsys and ytsys
                ut = preamble[1]
                xtsys.append(uv['xsampler'])
                ytsys.append(uv['ysampler'])
                utd.append(ut - 2400000.5)
    utd = np.array(utd)
    xtsys = np.array(xtsys)
    xtsys.shape = (len(utd), len(fghz), nants)
    ytsys = np.array(ytsys)
    ytsys.shape = (len(utd), len(fghz), nants)
    tsys = np.array((xtsys, ytsys))
    tsys = np.swapaxes(tsys, 1, 3)  # Order is now npol, nants, nf, nt
    tsys = np.swapaxes(tsys, 0, 1)  # Order is now nants, npol, nf, nt, as desired
    good, = np.where(tsys.sum(0).sum(0).sum(1) != 0.0)
    tsys = tsys[:, :, good, :]
    fghz = fghz[good]
    return {'source': src, 'fghz': fghz, 'ut_mjd': utd, 'tsys': tsys}


def rd_fdb(t):
    ''' Read the FDB file for the date given in Time() object t, and return in a
        useful dictionary form.
    '''
    # First try to read from IFDB file (on pipeline)
    try:
        fdb = rd_ifdb(t)
        if fdb != {}:
            # File was found and a non-empty dictionary resulted, so...success?
            return fdb
    except:
        pass

    # Check for existence of /data1/FDB, or use /dppdata1/FDB if not found:
    folder = '/data1/FDB'
    if glob.glob(folder) == []:
        folder = '/dppdata1/FDB'
    fdbfile = '/FDB' + t.iso[:10].replace('-', '') + '.txt'
    try:
        f = open(folder + fdbfile, 'r')
        lines = f.readlines()
        f.close()
    except:
        print('Error: Could not open file', folder + fdbfile + '.')
        return {}
    names = lines[0].replace(':', '').split()
    contents = np.zeros((len(names), len(lines) // 2), 'U32')
    for i in range(1, len(lines), 2):
        try:
            contents[:, (i - 1) // 2] = np.array(lines[i].split() + lines[i + 1].split())
        except:
            # If the above assignment does not work, line is malformed, so just
            # leave as empty list
            pass
    return dict(list(zip(names, contents)))

def rd_ifdb(t):
    ''' Read the IFDB file for the date given in Time() object t, and return in a
        useful dictionary form.
    '''
    # Check for existence of /data1/IFDB, or use /dppdata1/FDB if not found:
    yy = t.iso[:4]
    folder = '/data1/IFDB/'+yy
    fdbfile = '/IFDB' + t.iso[:10].replace('-', '') + '.txt'
    try:
        f = open(folder + fdbfile, 'r')
        lines = f.readlines()
        f.close()
    except:
        print('Error: Could not open IFDB file', folder + fdbfile + '. Will try FDB file.')
        return {}
    names = lines[0].replace(':', '').split()
    contents = np.zeros((len(names), len(lines)), 'U32')
    for i in range(1, len(lines)):
        try:
            contents[:, i-1] = np.array(lines[i].split())
        except:
            # If the above assignment does not work, line is malformed, so just
            # leave as empty list
            pass
    return dict(list(zip(names, contents)))

def rd_ufdb(t):
    ''' Read the UFDB file for the date given in Time() object t, and return in a
        useful dictionary form.
    '''
    folder = '/data1/UFDB/'
    ufdbfile = t.iso[:4] + '/UFDB' + t.iso[:10].replace('-', '') + '.txt'
    try:
        f = open(folder + ufdbfile, 'r')
        lines = f.readlines()
        f.close()
    except:
        print('Error: Could not open file', folder + ufdbfile + '.')
        return {}
    names = lines[0].replace(':', '').split()
    contents = np.zeros((len(names), len(lines) - 1), 'U32')
    for i in range(1, len(lines)):
        try:
            contents[:, i - 1] = np.array(lines[i].split())
        except:
            # If the above assignment does not work, line is malformed, so just
            # leave as empty list
            pass
    return dict(list(zip(names, contents)))

def get_projects(t, nosql=False):
    ''' Read all projects from SQL for the current date and return a summary
        as a dictionary with keys Timestamp, Project, and EOS (another timestamp)
    '''
    if nosql == True:
        return get_projects_nosql(t)
    from . import dbutil
    # timerange is 12 UT to 12 UT on next day, relative to the day in Time() object t
    trange = Time([int(t.mjd) + 12./24,int(t.mjd) + 36./24],format='mjd')
    tstart, tend = trange.lv.astype('str')
    cnxn, cursor = dbutil.get_cursor()
    mjd = t.mjd
    # Get the project IDs for scans during the period
    verstrh = dbutil.find_table_version(cursor,trange[0].lv,True)
    if verstrh is None:
        print('No scan_header table found for given time.')
        return {}
    query = 'select Timestamp,Project from hV'+verstrh+'_vD1 where Timestamp between '+tstart+' and '+tend+' order by Timestamp'
    projdict, msg = dbutil.do_query(cursor, query)
    if msg != 'Success':
        print(msg)
        return {}
    elif len(projdict) == 0:
        # No Project ID found, so return data and empty projdict dictionary
        print('SQL Query was valid, but no Project data were found.')
        return {}
    projdict['Timestamp'] = projdict['Timestamp'].astype('float')  # Convert timestamps from string to float
    for i in range(len(projdict['Project'])): projdict['Project'][i] = projdict['Project'][i].replace('\x00','')
    projdict.update({'EOS':projdict['Timestamp'][1:]})
    projdict.update({'Timestamp':projdict['Timestamp'][:-1]})
    projdict.update({'Project':projdict['Project'][:-1]})
    cnxn.close()
    return projdict

def get_projects_nosql(t):
    ''' Read all projects from FDB file for the current date and return a summary
        as a dictionary with keys Timestamp, Project, and EOS (another timestamp)
    '''
    # timerange is 12 UT to 12 UT on next day, relative to the day in Time() object t
    trange = Time([int(t.mjd) + 12./24,int(t.mjd) + 36./24],format='mjd')
    tstart = t.iso[2:10].replace('-','')+'120000'
    t2 = Time(int(t.mjd)+1, format='mjd')
    tend = t2.iso[2:10].replace('-','')+'120000'
    fdb = rd_fdb(t)
    fdb2 = rd_fdb(t2)
    if fdb == {}:
        # No FDB file found, so return empty project dictionary
        print('No Project data [FDB file] found for the given date.')
        return {}
    if fdb == {}:
        pass
    else:
        #  Concatenate the two dicts into one
        fdb = dict([(k, np.concatenate((fdb.get(k,[]),fdb2.get(k,[])))) for k in set(fdb)|set(fdb2)])  
    # Get "good" indexes for times between 12 UT on date and 12 UT on next date
    gidx, = np.where(np.logical_and(fdb['SCANID']>tstart,fdb['SCANID']<tend))        
    scanid,idx = np.unique(fdb['SCANID'][gidx],return_index=True)
    sidx = gidx[idx]   # Indexes into fdb for the start of each scan
    # Get the project IDs for scans during the period
    projdict = {'Timestamp':fdb['ST_TS'][sidx].astype(float),
                'Project':fdb['PROJECTID'][sidx],
                'EOS':fdb['EN_TS'][sidx].astype(float)}
    return projdict

def findfile(trange):

    from .util import nearest_val_idx
    import struct, time, glob, sys, socket

    host = socket.gethostname()
    if host == 'dpp':
        fpath = '/data1/IDB/'
    else:
        fpath = get_idbdir(trange[0])
    t1 = str(trange[0].mjd)
    t2 = str(trange[1].mjd)
    tnow = Time.now()

    if t1[:5] != t2[:5]:
        # End day is different than start day, so read and concatenate two fdb files
        fdb = {}
        fdb1 = rd_fdb(trange[0])
        fdb2 = rd_fdb(trange[1])
        for key in list(fdb1.keys()):
            fdb.update({key:np.append(fdb1[key],fdb2[key])})
    else:
        # Both start and end times are on the same day
        fdb = rd_fdb(trange[0])

    scanidx, = np.where(fdb['PROJECTID'] == 'PHASECAL')
    scans,sidx = np.unique(fdb['SCANID'][scanidx],return_index=True)
    eidx = np.append(sidx[1:],len(scanidx)) - 1
    # List of PHASECAL scan start times
    tslist = Time(fdb['ST_TS'][scanidx[sidx]].astype(float).astype(int),format='lv')
    # List of PHASECAL scan end times
    telist = Time(fdb['EN_TS'][scanidx[eidx]].astype(float).astype(int),format='lv')
    # Remove any bad values (i.e. those with ST_SEC = 0)
    try:
        good, = np.where(fdb['ST_SEC'][scanidx[sidx]] != '0')
        tslist = tslist[good]
        telist = telist[good]
    except KeyError:
        # Key 'ST_SEC' not found so just continue (this happens on pipeline when IFDB file is used)
        pass
        
    k = 0         # Number of scans within timerange
    m = 0         # Pointer to first scan within timerange
    flist = []
    status = []
    tstlist = []
    for i in range(len(tslist)):
        if tslist[i].jd >= trange[0].jd and telist[i].jd <= trange[1].jd:
            # Time is in range, so add it
            k += 1
        else:
            # Time is too early, so skip it
            m += 1
        
    if k == 0: 
        print('No phase calibration data within given time range')
        return None
    else: 
        print('Found',k,'scans in timerange.')
        for i in range(k):
            f1 = fdb['FILE'][np.where(fdb['SCANID'] == scans[m+i])].astype('str')
            # if fpath == '/data1/eovsa/fits/IDB/':
            #     f2 = [fpath + f[3:11] + '/' + f for f in f1]
            # else:
            #     f2 = [fpath + f for f in f1]
            if host == 'dpp':
                f2 = [fpath + f for f in f1]
            else:
                f2 = [fpath + f[3:11] + '/' + f for f in f1]
            flist.append(f2)
            tstlist.append(tslist[m+i])
            ted = telist[m+i]
            # Mark all files done except possibly the last
            fstatus = ['done']*len(f1)
            # Check if last file end time is less than 10 min ago
            if (tnow.jd - ted.jd) < (600./86400):
                # Current time is less than 10 min after this scan
                fstatus[-1] = 'undone'
            status.append(fstatus)

    return {'scanlist':flist,'status':status,'tstlist':tstlist}
    
if __name__ == "__main__":
    def usage(instr):
        print(instr)
        print('Usage:  dump_tsys <date1> <date2>')
        print('   e.g. dump_tsys "2014-11-16 16:00:00" "2014-11-16 17:00:00"')
        exit()


    arglist = str(sys.argv)
    if len(sys.argv) < 3:
        usage('No times listed')
    try:
        t1 = Time(sys.argv[1])
    except:
        print(sys.argv[1])
        usage('First argument not recognized as a valid time string')
    try:
        t2 = Time(sys.argv[2])
    except:
        print(sys.argv[2])
        usage('Second argument not recognized as a valid time string')

    dump_tsys(Time([t1.iso, t2.iso]))
