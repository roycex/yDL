import configparser
import sqlite3
import os
import yifile
import datetime
import time

class inifile:
    __configpath = ""
    yifilelist = ""
    downloadpath = ""
    datasource = ""

    def __init__(self, confile):
        if os.path.exists(confile):
            self.__configpath = confile
            config = configparser.ConfigParser()
            config.read(self.__configpath)
            self.yifilelist = config.get("yifiletool", "yifilelist")
            self.downloadpath = config.get("yifiletool", "downloadpath")
            if not os.path.exists(self.downloadpath):
                os.makedirs(self.downloadpath)
            self.datasource = config.get("yifiletool", "datasource")
            if os.path.exists(self.datasource):
                if os.path.isfile(self.datasource):
                    pass
                else:
                    raise FileExistsError(self.datasource + " is NOT a file")
            else:
                p, f = os.path.split(self.datasource)
                if p and not os.path.exists(p):
                    os.makedirs(p)
            self.__initDB()
        else:
            raise FileNotFoundError("Init file does NOT exist")

    def __initDB(self):
        conn = sqlite3.connect(self.datasource)
        sql = "select * from sqlite_master where type = 'table' and tbl_name = 'filelist'"
        c = conn.execute(sql)
        if c.fetchall().__len__() < 1:
            sql = "CREATE TABLE filelist (filepage text primary key,pagefilename text,pagefilesize text,filelink text,filename text,filesize integer,filepath text,downloadfolder text,downloadsize INTEGER , unzippath text, timecost INTEGER,starttime text,downloadtime text, unziptime text,endtime text,status integer)"
            conn.execute(sql)
            conn.commit()
        conn.close()

def getyifileList(yifilelistfile):
    """读取链接清单：每行一列（Tab 分隔），首列须为 yifile 链接（支持 /f/ 短链与 /file/ 长链，# 开头为注释）。
    注意：链接 # 后的 16 位片段是防盗链 key，必须完整保留。"""
    url_list = []
    if os.path.exists(yifilelistfile):
        with open(yifilelistfile, encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                url = line.split("\t")[0].strip()
                low = url.lower()
                if "yifile.com/f/" in low or "yifile.com/file/" in low:
                    url_list.append(url)
                else:
                    print("skip invalid link:", url)
    return url_list

def insertYifile(page, size, name):
    conn = sqlite3.connect(config.datasource)
    sql = "select * from filelist where filepage = ? or pagefilesize = ?"
    c = conn.execute(sql, (page, size))
    if c.fetchall().__len__() < 1:
        sql = "insert into filelist (filepage, pagefilename,pagefilesize,downloadfolder,starttime,status) VALUES (?,?,?,?,?,0)"
        conn.execute(sql, (page, name, size, config.downloadpath, getdatetime()))
        conn.commit()
    conn.close()

def formatFileSize(size):
    size = float(size)
    if (size >= 1024) and (size <= 1024 * 1024):
        f = "%.2f KB" % (float(size) / 1024)
    elif (size >= 1024 * 1024) and (size < 1024 * 1024 * 1024):
        f = "%.2f MB" % (float(size) / 1024 / 1024)
    elif (size >= (1024 * 1024 * 1024)):
        f = "%.2f GB" % (float(size) / 1024 / 1024 / 1024)
    else:
        f = "%d Bytes" % (size)
    return f

def getdatetime():
    return str(datetime.datetime.now())

def getdownloadinglist():
    list = []
    sql = "select filepage, pagefilename, pagefilesize, filelink, filename, filesize, filepath, downloadsize, timecost,downloadfolder,status from filelist where status = 1 order by starttime "
    conn = sqlite3.connect(config.datasource)
    c = conn.execute(sql)
    rows = c.fetchall()
    for r in rows:
        y = yifile.yifile(r[0])
        y.pagefilename = r[1]
        y.pagefilesize = r[2]
        y.filelink = r[3]
        y.filename = r[4]
        y.filesize = r[5]
        y.filepath = r[6]
        y.downloadsize = r[7]
        y.timecost = r[8]
        y.downloadfolder = r[9]
        y.status = r[10]
        if os.path.exists(y.filepath):
            if y.downloadsize == os.path.getsize(y.filepath):
                list.append(y)
            else:
                y.downloadsize = os.path.getsize(y.filepath)
                sql = "update filelist set downloadsize = ? where filepage = ?"
                conn.execute(sql, (y.downloadsize, y.filepage))
                conn.commit()
                list.append(y)
        else:
            sql = "update filelist set status = 0 where filepage = ?"
            conn.execute(sql, (y.filepage,))
            conn.commit()
    conn.close()
    return list

def getdownloadlist():
    list = []
    sql = "select filepage from filelist where status = 0 order by starttime "
    # sql = "select filepage from filelist where status < 2 order by status DESC , starttime "
    conn = sqlite3.connect(config.datasource)
    c = conn.execute(sql)
    rows = c.fetchall()
    for r in rows:
        list.append(r[0])
    conn.close()
    return list

def uptyifileinfo(yifile):
    sql = "update filelist set filelink = ?,filename = ?,filesize = ?,filepath = ?,downloadsize = ?,timecost = ?,status = ?"
    params = [yifile.filelink, yifile.filename, yifile.filesize, yifile.filepath,
              yifile.downloadsize, yifile.timecost, yifile.status]
    if yifile.downloadtime:
        sql += ",downloadtime = ?"
        params.append(yifile.downloadtime)
    if yifile.unziptime:
        sql += ",unziptime = ?"
        params.append(yifile.unziptime)
    if yifile.endtime:
        sql += ",endtime = ?"
        params.append(yifile.endtime)
    sql += " where filepage = ?"
    params.append(yifile.filepage)
    conn = sqlite3.connect(config.datasource)
    conn.execute(sql, params)
    conn.commit()
    conn.close()

if __name__ == '__main__':
    try:
        print("application start")
        mainpath = os.path.abspath(os.curdir)
        ini = mainpath + "\\main.ini"
        config = inifile(ini)
        yifilelist = getyifileList(config.yifilelist)
        print("loaded %d link(s) from list" % len(yifilelist))
        print("get config")
        for y in yifilelist:
            try:
                yi = yifile.yifile(y)
                yi.getyifilePageInfo()
                # filepage 含 # 防盗链片段，下载阶段据此恢复 key
                insertYifile(yi.filepage, yi.pagefilesize, yi.pagefilename)
            except Exception as e:
                print("skip invalid page:", y, "->", e)
                continue
        print("insert yifile initial info")
        list = getdownloadinglist()
        print("get downloading yifile data" + "\t" + str(list.__len__()))
        for l in list:
            tries = 0
            while l.status != 2:
                if l.status == 2:
                    break
                elif l.status == -1:
                    tries += 1
                    if tries >= 5:
                        print("retry limit reached, skip:", l.filepage)
                        break
                    l.continueDownloading(uptcallback=uptyifileinfo)
                elif l.status == 1:
                    tries += 1
                    if tries >= 5:
                        print("retry limit reached, skip:", l.filepage)
                        break
                    l.continueDownloading(uptcallback=uptyifileinfo)
                else:
                    break
            # l.continueDownloading(uptcallback=uptyifileinfo)
            uptyifileinfo(l)
        list = getdownloadlist()
        print("get new yifile data" + "\t" + str(list.__len__()))
        for l in list:
            try:
                y = yifile.yifile(l)
                y.downloadfolder = config.downloadpath
                r = 0
                zero_count = 0
                while r != 2:
                    if r == 2:
                        break
                    elif r == -1:
                        print(r)
                        time.sleep(600)
                        r = y.continueDownloading(uptcallback=uptyifileinfo)
                    elif r == 1:
                        print(r)
                        r = y.continueDownloading(uptcallback=uptyifileinfo)
                    elif r == 0:
                        zero_count += 1
                        if zero_count >= 3:
                            print("consecutively failed to get download link, skip:", l)
                            break
                        r = y.startdownload(uptcallback=uptyifileinfo)
                    else:
                        break
                # r = y.startdownload(uptcallback=uptyifileinfo)
                uptyifileinfo(y)
            except Exception as e:
                print("download failed:", l, "->", e)
                continue
        print("all tasks finished")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("application error:", e)
    finally:
        # 双击运行时保持窗口打开，便于查看结果
        try:
            input("\n按回车键退出...")
        except EOFError:
            pass


