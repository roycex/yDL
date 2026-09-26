import urllib
from PIL import Image
import http.cookiejar
import os
import re
from captcha_ocr import recognize
import time
import io
import urllib.request
import urllib.response
import datetime
import zipfile
import threading

class yifile:
    filepage = ""
    pagefilename = ""
    pagefilesize = ""
    filelink = ""
    filename = ""
    filesize = 0
    downloadfolder = ""
    filepath = ""
    downloadsize = 0
    unzippath = ""
    timecost = 0
    starttime = ""
    downloadtime = ""
    unziptime = ""
    endtime = ""
    status = 0
    __fileid = 0
    __fileaction = ""
    __codelink = "https://www.yifile.com/includes/imgcode.inc.php?verycode_type=2"
    __codeurl = "https://www.yifile.com/ajax.php"
    __freedlurl = "https://www.yifile.com/jsa/freedl.php"

    def __init__(self, url):
        # 分享链接 # 后的 16 位片段是防盗链 key（浏览器端 hijackDownload 会将其
        # 附加为下载直链的 &k= 参数，服务端校验失败返回 403/400），必须保留
        base, _, frag = url.partition('#')
        self.filepage = url            # 完整链接（含片段，与任务库 filepage 一致）
        self.pagebase = base           # 去掉片段的页面地址（用于 HTTP 请求与 referer）
        self.dlk = frag[:16] if len(frag) >= 16 else ''
        self.__fileaction = "yifile_down"
        # 每个文件独立会话：类级共享 CookieJar 时，第二个文件会复用第一个文件
        # 已兑换过直链的会话，验证码校验会被服务端持续拒绝
        self.__cookie = http.cookiejar.CookieJar()

    def __getyifilePage(self):
        req = urllib.request.Request(self.pagebase)
        req.add_header('accept',
                       'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8')
        req.add_header('accept-language', 'en-US,en;q=0.8,zh-TW;q=0.6,zh;q=0.4,zh-CN;q=0.2')
        req.add_header('cache-control', 'max-age=0')
        req.add_header('user-agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36' +
                       ' (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36')
        # 带 cookie 访问，保证会话与后续 freedl/验证码请求一致
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.__cookie))
        rep = opener.open(req, timeout=30)
        return rep.read().decode('utf-8', errors='replace')

    def getyifilePageInfo(self):
        pagecode = self.__getyifilePage()
        p = re.compile('<span id="FileSize">.*?</span>')
        s = p.findall(pagecode)[0]
        self.pagefilesize = s[s.find(">") + 1: s.rfind("<")]
        p = re.compile('<span id=\"FileName\".*?</span>')
        n = p.findall(pagecode)[0]
        self.pagefilename = n[n.find(">") + 1: n.rfind("<")]
        return self.pagefilesize, self.pagefilename

    def __getFileKey(self):
        """从文件页提取 file_key（站点 2024+ 接口已由数字 file_id 改为短码 file_key）"""
        pagecode = self.__getyifilePage()
        m = re.search(r'action=yifile_down&(?:amp;)?file_key=([0-9a-zA-Z]+)', pagecode)
        if m:
            return m.group(1)
        # 兜底：短链 /f/<key> 或长链 /file/<key>
        m = re.search(r'yifile\.com/(?:f|file)/([0-9a-zA-Z]+)', self.pagebase)
        if m:
            return m.group(1)
        raise ValueError("页面中未找到 file_key，链接可能已失效: " + self.filepage)

    def __getVeryCode(self):
        """获取验证码原始图片（彩色），识别交给 captcha_ocr.recognize"""
        vreq = urllib.request.Request(self.__codelink)
        vreq.add_header('accept',
                        'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8')
        vreq.add_header('accept-language', 'en-US,en;q=0.8,zh-TW;q=0.6,zh;q=0.4,zh-CN;q=0.2')
        vreq.add_header('cache-control', 'max-age=0')
        vreq.add_header('user-agent', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36' +
                        ' (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36')
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.__cookie))
        response = opener.open(vreq)
        data_stream = io.BytesIO(response.read())
        pil_image = Image.open(data_stream)
        return pil_image.convert('RGB')

    def __freedl(self):
        """免费下载预检：POST /jsa/freedl.php 在服务端建立下载会话。
        2024+ 新流程：freedl 返回 true 后站点强制 30 秒倒计时，之后才接受验证码提交。"""
        postdata = urllib.parse.urlencode({'file_key': self.__fileid}).encode()
        postheader = {
            'accept': 'text/plain, */*; q=0.01',
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.181 Safari/537.36',
            'x-requested-with': 'XMLHttpRequest',
            'origin': 'https://www.yifile.com',
            'referer': self.pagebase
        }
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.__cookie))
        req = urllib.request.Request(url=self.__freedlurl, data=postdata, headers=postheader, method='POST')
        response = opener.open(req, timeout=30)
        s = response.read()
        print("freedl:", s[:60])
        return s.split(b"|")[0] == b'true'

    def getYifileLink(self, trytimes=0):
        self.__fileid = self.__getFileKey()
        # 第一步：免费下载预检
        if not self.__freedl():
            print("freedl 预检未通过（可能达到当日免费下载次数限制）:", self.filepage)
            return 0
        # 第二步：站点强制 30 秒倒计时后才接受验证码
        print("waiting 31s for site countdown ...")
        time.sleep(31)
        # 第三步：验证码换直链
        verified = 0
        if trytimes <= 0:
            trytimes = 1
        for i in range(trytimes):
            verycode = recognize(self.__getVeryCode())
            if not verycode:
                time.sleep(1)
                continue
            # 按识别原样提交（已验证大写字形原样可通过）
            postdata = {
                'action': self.__fileaction,
                'file_key': self.__fileid,
                'verycode': verycode
            }
            postheader = {
                'accept': 'text/plain, */*; q=0.01',
                # 'accept-encoding': 'gzip, deflate, br',
                # 'accept-language': 'en-US,en;q=0.8,zh-TW;q=0.6,zh;q=0.4,zh-CN;q=0.2',
                'accept-language': 'en-US,en;q=0.9,zh-TW;q=0.8,zh;q=0.7,zh-CN;q=0.6',
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                # 'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36' +
                #              ' (KHTML, like Gecko) Chrome/60.0.3112.113 Safari/537.36',
                'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_13_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/65.0.3325.181 Safari/537.36',
                'x-requested-with': 'XMLHttpRequest',
                'origin': 'https://www.yifile.com',
                'referer': self.pagebase
            }
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.__cookie))
            req = urllib.request.Request(url=self.__codeurl, data=urllib.parse.urlencode(postdata).encode(), headers=postheader, method='POST')
            response = opener.open(req)
            s = response.read()
            result = s.split(b"|", 1)
            print("verify:", result[0])
            if result[0] == b'true':
                self.filelink = result[1].decode()
                # 新直链形如 freedown.php?path=...&name=xxx.rar&e=...，从 name 参数取文件名
                m = re.search(r'[?&]name=([^&]+)', self.filelink)
                if m:
                    self.filename = urllib.parse.unquote(m.group(1))
                else:
                    self.filename = self.filelink.split('/')[-1].split('?')[0]
                # 附加分享链接 # 片段对应的防盗链 key（缺失会 403）
                if self.dlk:
                    self.filelink = self.filelink + '&k=' + urllib.parse.quote(self.dlk)
                verified = 1
                break
            time.sleep(1)
        return verified

    def continueDownloading(self, uptcallback=None):
        print("start continue downloading " + self.filename + "\t" + yifile.formatFileSize(self.downloadsize) + "\\" + yifile.formatFileSize(self.filesize))
        if self.downloadsize == self.filesize and self.filesize > 0:
            if self.filepath.find('.downloading') >= 0:
                try:
                    os.rename(self.filepath, self.downloadfolder + "\\" + self.filename)
                    self.filepath = self.downloadfolder + "\\" + self.filename
                except FileExistsError:
                    os.rename(self.filepath, self.filepath.replace(".downloading", ""))
                    self.filepath = self.filepath.replace(".downloading", "")
            self.status = 2
            print("\n download finished " + self.filename + "\t" + yifile.formatFileSize(
                self.downloadsize) + "\\" + yifile.formatFileSize(self.filesize))
            return self.status
        # 新版下载服务器不支持 Range 断点续传（403 "range not allowed"），
        # 未完成的任务降级为从头重新下载（覆盖原 .downloading 文件）
        print("server does not support resume, restart from scratch")
        self.downloadsize = 0
        self.filesize = 0
        return self.startdownload(uptcallback)

    def startdownload(self, uptcallback=None):
        if self.getYifileLink(10) == 1:
            print("start downloading " + self.filename + "\t" + yifile.formatFileSize(self.filesize))
            if os.path.exists(self.downloadfolder + "\\" + self.filename):
                self.filename = time.strftime('%Y%m%d%H%M%S') + self.filename
            self.filepath = self.downloadfolder + "\\" + self.filename + ".downloading"
            # 浏览器级请求头（缺失会被下载服务器拒绝）
            headers = {
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
                'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'referer': self.pagebase,
            }
            # 直链自包含鉴权参数（e/key/xcode/k），不携带站点会话 cookie（带 cookie 反而被拒）
            req = urllib.request.Request(url=self.filelink, data=None,
                                         headers=headers, method='GET')
            rep = urllib.request.urlopen(req, timeout=60)
            self.filesize = rep.headers["Content-Length"]
            if uptcallback:
                uptcallback(self)
            f = open(self.filepath, "wb+")
            start = time.time()
            file_size_dl = 0
            block_sz = 65536
            uptcounter = 0
            self.downloadtime = str(datetime.datetime.now())
            try:
                while True:
                    buffer = rep.read(block_sz)
                    if not buffer:
                        break
                    file_size_dl += len(buffer)
                    self.downloadsize = file_size_dl
                    f.write(buffer)
                    self.status = 1
                    end = time.time()
                    time.sleep(0.05)
                    self.timecost = round((end - start))
                    if self.timecost < 1:
                        self.timecost = 1
                    if uptcounter == 100:
                        uptcallback(self)
                        uptcounter = 0
                    speed = int(file_size_dl / self.timecost)
                    print("%s:%.2f%% %s/%s %s S %s/S     " % (
                        self.filename, float(self.downloadsize) / float(self.filesize) * 100,
                        yifile.formatFileSize(self.downloadsize), yifile.formatFileSize(self.filesize),
                        str(self.timecost), yifile.formatFileSize(speed)), end="\r")
                    uptcounter += 1
                f.close()
                self.status = 2
                os.rename(self.filepath, self.downloadfolder + "\\" + self.filename)
                self.filepath = self.downloadfolder + "\\" + self.filename
                print("\n download finished " + self.filename + "\t" + yifile.formatFileSize(
                    self.downloadsize) + "\\" + yifile.formatFileSize(self.filesize))
                return self.status
            except Exception as e:
                self.status = 1
                print("\n")
                print("download error: " + str(e))
                if str(e).find("WinError 10054") > 0:
                    return -1
                return self.status
            finally:
                if not f.closed:
                    f.close()
        else:
            return 0



    def formatFileSize(size):
        size = float(size)
        if (size >= 1024) and (size <= 1024 * 1024):
            f = "%.2f KB" % (float(size) / 1024)
        elif (size >= 1024 * 1024) and (size < 1024 * 1024 * 1024):
            f = "%.2f MB" % (float(size) / 1024 / 1024)
        elif size >= (1024 * 1024 * 1024):
            f = "%.2f GB" % (float(size) / 1024 / 1024 / 1024)
        else:
            f = "%d Bytes" % size
        return f