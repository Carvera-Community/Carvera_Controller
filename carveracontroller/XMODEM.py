from __future__ import division, print_function
import platform, logging, time, sys, math, struct
from functools import partial
from enum import Enum, auto
FRAME_HEADER = 34408
FRAME_END = 21930
PTYPE_CTRL_SINGLE = 161
PTYPE_CTRL_MULTI = 162
PTYPE_FILE_MD5 = 177
PTYPE_FILE_VIEW = 178
PTYPE_FILE_DATA = 179
PTYPE_FILE_END = 180
PTYPE_FILE_CAN = 181
PTYPE_FILE_RETRY = 182

class RevPacketState(Enum):
    WAIT_HEADER = auto()
    READ_LENGTH = auto()
    READ_DATA = auto()
    CHECK_FOOTER = auto()


class FileTransState(Enum):
    WAIT_MD5 = auto()
    WAIT_FILE_VIEW = auto()
    READ_FILE_DATA = auto()


class XMODEM(object):
    crctable = [
     0, 4129, 8258, 12387, 16516, 20645, 24774, 28903, 
     33032, 
     37161, 41290, 45419, 49548, 53677, 57806, 61935, 
     4657, 
     528, 12915, 8786, 21173, 17044, 29431, 25302, 
     37689, 
     33560, 45947, 41818, 54205, 50076, 62463, 58334, 
     9314, 
     13379, 1056, 5121, 25830, 29895, 17572, 21637, 
     42346, 
     46411, 34088, 38153, 58862, 62927, 50604, 54669, 
     13907, 
     9842, 5649, 1584, 30423, 26358, 22165, 18100, 
     46939, 
     42874, 38681, 34616, 63455, 59390, 55197, 51132, 
     18628, 
     22757, 26758, 30887, 2112, 6241, 10242, 14371, 
     51660, 
     55789, 59790, 63919, 35144, 39273, 43274, 47403, 
     23285, 
     19156, 31415, 27286, 6769, 2640, 14899, 10770, 
     56317, 
     52188, 64447, 60318, 39801, 35672, 47931, 43802, 
     27814, 
     31879, 19684, 23749, 11298, 15363, 3168, 7233, 
     60846, 
     64911, 52716, 56781, 44330, 48395, 36200, 40265, 
     32407, 
     28342, 24277, 20212, 15891, 11826, 7761, 3696, 
     65439, 
     61374, 57309, 53244, 48923, 44858, 40793, 36728, 
     37256, 
     33193, 45514, 41451, 53516, 49453, 61774, 57711, 
     4224, 
     161, 12482, 8419, 20484, 16421, 28742, 24679, 
     33721, 
     37784, 41979, 46042, 49981, 54044, 58239, 62302, 
     689, 
     4752, 8947, 13010, 16949, 21012, 25207, 29270, 
     46570, 
     42443, 38312, 34185, 62830, 58703, 54572, 50445, 
     13538, 
     9411, 5280, 1153, 29798, 25671, 21540, 17413, 
     42971, 
     47098, 34713, 38840, 59231, 63358, 50973, 55100, 
     9939, 
     14066, 1681, 5808, 26199, 30326, 17941, 22068, 
     55628, 
     51565, 63758, 59695, 39368, 35305, 47498, 43435, 
     22596, 
     18533, 30726, 26663, 6336, 2273, 14466, 10403, 
     52093, 
     56156, 60223, 64286, 35833, 39896, 43963, 48026, 
     19061, 
     23124, 27191, 31254, 2801, 6864, 10931, 14994, 
     64814, 
     60687, 56684, 52557, 48554, 44427, 40424, 36297, 
     31782, 
     27655, 23652, 19525, 15522, 11395, 7392, 3265, 
     61215, 
     65342, 53085, 57212, 44955, 49082, 36825, 40952, 
     28183, 
     32310, 20053, 24180, 11923, 16050, 3793, 7920]

    def __init__(self, getc, putc, mode='wifiMode', pad=b'\x1a'):
        self.getc = getc
        self.putc = putc
        self.mode = mode
        self.mode_set = False
        self.pad = pad
        self.log = logging.getLogger("xmodem.XMODEM")
        self.canceled = False
        self.currentState = RevPacketState.WAIT_HEADER
        self.packetData = bytearray()
        self.headerBuffer = bytearray(2)
        self.footerBuffer = bytearray(2)
        self.bytesNeeded = 2
        self.expectedLength = 0
        self.FileRcvState = FileTransState.WAIT_MD5

    def clear_mode_set(self):
        self.mode_set = False

    def abort(self, count=2, timeout=60):
        self.SendFileTransCommand(PTYPE_FILE_CAN, b'')

    def crc16_ccitt(self, data: bytes, length: int) -> int:
        crc = 0
        for i in range(length):
            tmp = (crc >> 8 ^ data[i]) & 255
            crc = (crc << 8 ^ self.crctable[tmp]) & 65535

        return crc & 65535

    def recvPacket(self, timeout=0.5):
        self.currentState = RevPacketState.WAIT_HEADER
        tr = time.time()
        while True:
            byte = self.getc(1, timeout)
            if byte:
                byte = ord(byte)
                if self.currentState == RevPacketState.WAIT_HEADER:
                    self.headerBuffer[0] = self.headerBuffer[1]
                    self.headerBuffer[1] = byte
                    checksum = self.headerBuffer[0] << 8 | self.headerBuffer[1]
                    if checksum == FRAME_HEADER:
                        self.currentState = RevPacketState.READ_LENGTH
                        self.bytesNeeded = 2
                        self.packetData.clear()
                elif self.currentState == RevPacketState.READ_LENGTH:
                    self.packetData.append(byte)
                    self.bytesNeeded -= 1
                    if self.bytesNeeded == 0:
                        self.expectedLength = self.packetData[0] << 8 | self.packetData[1]
                        self.currentState = RevPacketState.READ_DATA
                        self.bytesNeeded = self.expectedLength
                elif self.currentState == RevPacketState.READ_DATA:
                    self.packetData.append(byte)
                    self.bytesNeeded -= 1
                    while self.bytesNeeded > 0:
                        bytess = self.getc(self.bytesNeeded, timeout)
                        if bytess:
                            self.packetData.extend(bytess)
                            self.bytesNeeded = 0
                        else:
                            return
                    if self.bytesNeeded == 0:
                        self.currentState = RevPacketState.CHECK_FOOTER
                        self.bytesNeeded = 2
                elif self.currentState == RevPacketState.CHECK_FOOTER:
                    self.footerBuffer[0] = self.footerBuffer[1]
                    self.footerBuffer[1] = byte
                    self.bytesNeeded -= 1
                    if self.bytesNeeded == 0:
                        checksum = self.footerBuffer[0] << 8 | self.footerBuffer[1]
                        self.currentState = RevPacketState.WAIT_HEADER
                        if checksum == FRAME_END:
                            if self.process_packet():
                                return 1
                            return None
                        return None
            else:
                return

    def process_packet(self):
        if len(self.packetData) < 2:
            self.packetData.clear()
            return
        calcCRC = self.crc16_ccitt(self.packetData, len(self.packetData) - 2)
        receivedCRC = self.packetData[-2] << 8 | self.packetData[-1]
        if calcCRC == receivedCRC:
            if len(self.packetData) >= 3:
                return 1
            self.packetData.clear()
            return
        self.packetData.clear()
        return

    def SendFileTransCommand(self, Cmdstr, data: bytes) -> bytes:
        if not isinstance(data, bytes):
            raise TypeError("data 必须是 bytes 类型")
        DATA_LENGTH = 1 + len(data) + 2
        crc_payload = DATA_LENGTH.to_bytes(2, "big") + bytes([Cmdstr]) + data
        crc = self.crc16_ccitt(crc_payload, DATA_LENGTH)
        packet = FRAME_HEADER.to_bytes(2, "big") + DATA_LENGTH.to_bytes(2, "big") + bytes([Cmdstr]) + data + crc.to_bytes(2, "big") + FRAME_END.to_bytes(2, "big")
        self.putc(packet)

    def recv(self, stream, md5='', crc_mode=1, retry=5, timeout=5, delay=0.1, quiet=0, callback=None):
        success_count = 0
        error_count = 0
        totalerr_count = 0
        total_packet = 0
        packet_size = 0
        sequence = 0
        income_size = 0
        while 1:
            if self.canceled:
                self.SendFileTransCommand(PTYPE_FILE_CAN, b'')
                self.log.info("Transmission canceled by user.")
                self.canceled = False
                return -1
            result = self.recvPacket(timeout)
            if result:
                cmdType = self.packetData[2]
                if cmdType < PTYPE_FILE_MD5:
                    continue
                else:
                    if cmdType == PTYPE_FILE_CAN:
                        self.log.info("Transmission canceled by Machine.")
                        self.FileRcvState = FileTransState.WAIT_MD5
                        return
                    if self.FileRcvState == FileTransState.READ_FILE_DATA and self.packetData:
                        seq = self.packetData[3] << 24 | self.packetData[4] << 16 | self.packetData[5] << 8 | self.packetData[6]
                        if cmdType == PTYPE_FILE_DATA and sequence == seq:
                            data_len = (self.packetData[0] << 8 | self.packetData[1]) - 7
                            income_size += data_len
                            stream.write(self.packetData[7:data_len + 7])
                            if sequence < total_packet:
                                sequence += 1
                                data = sequence.to_bytes(4, byteorder="big", signed=False)
                                self.SendFileTransCommand(PTYPE_FILE_DATA, data)
                            success_count = success_count + 1
                            if callable(callback):
                                callback(seq, total_packet)
                            error_count = 0
                            totalerr_count = 0
                            if seq == total_packet:
                                self.SendFileTransCommand(PTYPE_FILE_END, b'')
                                self.FileRcvState = FileTransState.WAIT_MD5
                                self.log.info("Transmission complete, %d bytes", income_size)
                                self.FileRcvState = FileTransState.WAIT_MD5
                                return income_size
                        error_count += 1
                        if error_count >= retry:
                            data = sequence.to_bytes(4, byteorder="big", signed=False)
                            self.SendFileTransCommand(PTYPE_FILE_DATA, data)
                            totalerr_count += 1
                    if self.FileRcvState == FileTransState.WAIT_FILE_VIEW and self.packetData:
                        if cmdType == PTYPE_FILE_VIEW:
                            total_packet = self.packetData[3] << 24 | self.packetData[4] << 16 | self.packetData[5] << 8 | self.packetData[6]
                            packet_size = self.packetData[7] << 8 | self.packetData[8]
                            sequence = 1
                            data = sequence.to_bytes(4, byteorder="big", signed=False)
                            self.SendFileTransCommand(PTYPE_FILE_DATA, data)
                            self.FileRcvState = FileTransState.READ_FILE_DATA
                            error_count = 0
                            totalerr_count = 0
                        else:
                            error_count += 1
                            if error_count >= retry:
                                self.SendFileTransCommand(PTYPE_FILE_VIEW, b'')
                                totalerr_count += 1
                    if self.FileRcvState == FileTransState.WAIT_MD5 and self.packetData:
                        if cmdType == PTYPE_FILE_MD5:
                            md5new = self.packetData[3:len(self.packetData) - 2]
                            if md5.encode() == md5new and (not md5 == ""):
                                self.SendFileTransCommand(PTYPE_FILE_CAN, b'')
                                return 0
                            self.SendFileTransCommand(PTYPE_FILE_VIEW, b'')
                            self.FileRcvState = FileTransState.WAIT_FILE_VIEW
                            error_count = 0
                            totalerr_count = 0
                        error_count += 1
                        if error_count >= retry:
                            self.SendFileTransCommand(PTYPE_FILE_MD5, b'')
                            totalerr_count += 1
                    if self.canceled:
                        self.SendFileTransCommand(PTYPE_FILE_CAN, b'')
                        self.log.info("Transmission canceled by user.")
                        self.canceled = False
                        self.FileRcvState = FileTransState.WAIT_MD5
                        return
                    self.packetData.clear()
            else:
                error_count += 1
                if error_count >= 1:
                    totalerr_count += 1
                    self.SendFileTransCommand(PTYPE_FILE_RETRY, b'')
                    self.packetData.clear()
            if totalerr_count >= retry:
                self.SendFileTransCommand(PTYPE_FILE_CAN, b'')
                self.log.info("retry_count reached %d, aborting.", retry)
                self.abort(timeout=timeout)
                self.FileRcvState = FileTransState.WAIT_MD5
                return

    def send(self, stream, md5, retry=16, timeout=5, quiet=False, callback=None):
        td = float()
        lastseq = 0
        packetno = 0
        try:
            packet_size = dict(USBMode=128,
              wifiMode=8192)[self.mode]
        except KeyError:
            raise ValueError("Invalid mode specified: {self.mode!r}".format(self=self))

        data = md5.encode()
        self.SendFileTransCommand(PTYPE_FILE_MD5, data)
        lastcmd = PTYPE_FILE_MD5
        td = time.time()
        while 1:
            if self.canceled:
                self.SendFileTransCommand(PTYPE_FILE_CAN, b'')
                self.log.info("Transmission canceled by user.")
                self.canceled = False
                return
            result = self.recvPacket(timeout * 8)
            if result:
                td = time.time()
                cmdType = self.packetData[2]
                if cmdType < PTYPE_FILE_MD5:
                    continue
                if cmdType == PTYPE_FILE_CAN:
                    self.log.info("Transmission canceled by Machine.")
                    self.FileRcvState = FileTransState.WAIT_MD5
                    return
                if cmdType == PTYPE_FILE_RETRY:
                    self.SendFileTransCommand(lastcmd, data)
                if cmdType == PTYPE_FILE_MD5:
                    data = md5.encode()
                    self.SendFileTransCommand(PTYPE_FILE_MD5, data)
                if cmdType == PTYPE_FILE_VIEW:
                    stream.seek(0, 2)
                    file_size = stream.tell()
                    stream.seek(0)
                    packetno = math.ceil(file_size / packet_size)
                    packetno_bytes = struct.pack(">I", packetno)
                    packetsize_bytes = struct.pack(">H", packet_size)
                    data = packetno_bytes + packetsize_bytes
                    self.SendFileTransCommand(PTYPE_FILE_VIEW, data)
                    lastcmd = PTYPE_FILE_VIEW
                    lastseq = 0
                if cmdType == PTYPE_FILE_DATA:
                    seq = self.packetData[3] << 24 | self.packetData[4] << 16 | self.packetData[5] << 8 | self.packetData[6]
                    if seq == lastseq:
                        self.SendFileTransCommand(PTYPE_FILE_DATA, data)
                    elif seq == lastseq + 1:
                        seq_bytes = struct.pack(">I", seq)
                        file_data = stream.read(packet_size)
                        data = seq_bytes + file_data
                        self.SendFileTransCommand(PTYPE_FILE_DATA, data)
                    else:
                        seq_bytes = struct.pack(">I", seq)
                        stream.seek((seq - 1) * packet_size, 0)
                        file_data = stream.read(packet_size)
                        data = seq_bytes + file_data
                        self.SendFileTransCommand(PTYPE_FILE_DATA, data)
                    lastcmd = PTYPE_FILE_DATA
                    lastseq = seq
                    if callable(callback):
                        callback(packet_size, seq, 0, 0)
                if cmdType == PTYPE_FILE_END:
                    self.log.info("Transmission successful (FILE end flag received).")
                    return True
            else:
                t = time.time()
                if t - td > 9:
                    self.SendFileTransCommand(PTYPE_FILE_CAN, b'')
                    self.log.info("Info: Controller receive data timeout!")
                    self.FileRcvState = FileTransState.WAIT_MD5
                    return

    def _verify_recv_checksum(self, crc_mode, data):
        if crc_mode:
            _checksum = bytearray(data[(-2):])
            their_sum = (_checksum[0] << 8) + _checksum[1]
            data = data[:-2]
            our_sum = self.calc_crc(data)
            valid = bool(their_sum == our_sum)
            if not valid:
                self.log.warn("recv error: checksum fail (theirs=%04x, ours=%04x), ", their_sum, our_sum)
        else:
            _checksum = bytearray([data[-1]])
            their_sum = _checksum[0]
            data = data[:-1]
            our_sum = self.calc_checksum(data)
            valid = their_sum == our_sum
            if not valid:
                self.log.warn("recv error: checksum fail (theirs=%02x, ours=%02x)", their_sum, our_sum)
        return (valid, data)

    def calc_checksum(self, data, checksum=0):
        if platform.python_version_tuple() >= ('3', '0', '0'):
            return (sum(data) + checksum) % 256
        return (sum(map(ord, data)) + checksum) % 256

    def calc_crc(self, data, crc=0):
        for char in bytearray(data):
            crctbl_idx = (crc >> 8 ^ char) & 255
            crc = (crc << 8 ^ self.crctable[crctbl_idx]) & 65535

        return crc & 65535


def _send(mode='USBMode', filename=None, timeout=30):
    if filename is None:
        si = sys.stdin
    else:
        si = open(filename, "rb")
    so = sys.stdout

    def _getc(size, timeout=timeout):
        read_ready, _, _ = select.select([so], [], [], timeout)
        if read_ready:
            data = stream.read(size)
        else:
            data = None
        return data

    def _putc(data, timeout=timeout):
        _, write_ready, _ = select.select([], [si], [], timeout)
        if write_ready:
            si.write(data)
            si.flush()
            size = len(data)
        else:
            size = None
        return size

    xmodem = XMODEM(_getc, _putc, mode)
    return xmodem.send(si)


def run():
    import argparse, serial, sys
    platform = sys.platform.lower()
    if platform.startswith("win"):
        default_port = "COM1"
    else:
        default_port = "/dev/ttyS0"
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--port", default=default_port, help="serial port")
    parser.add_argument("-r", "--rate", default=9600, type=int, help="baud rate")
    parser.add_argument("-b", "--bytesize", default=(serial.EIGHTBITS), help="serial port transfer byte size")
    parser.add_argument("-P", "--parity", default=(serial.PARITY_NONE), help="serial port parity")
    parser.add_argument("-S", "--stopbits", default=(serial.STOPBITS_ONE), help="serial port stop bits")
    parser.add_argument("-m", "--mode", default="USBMode", help="XMODEM mode (USBMode, wifiMode)")
    parser.add_argument("-t", "--timeout", default=30, type=int, help="I/O timeout in seconds")
    subparsers = parser.add_subparsers(dest="subcommand")
    send_parser = subparsers.add_parser("send")
    send_parser.add_argument("filename", nargs="?", help="filename to send, empty reads from stdin")
    recv_parser = subparsers.add_parser("recv")
    recv_parser.add_argument("filename", nargs="?", help="filename to receive, empty sends to stdout")
    options = parser.parse_args()
    if options.subcommand == "send":
        return _send(options.mode, options.filename, options.timeout)
    if options.subcommand == "recv":
        return _recv(options.mode, options.filename, options.timeout)


def runx():
    import optparse, subprocess
    parser = optparse.OptionParser(usage="%prog [<options>] <send|recv> filename filename")
    parser.add_option("-m", "--mode", default="USBMode", help="XMODEM mode (USBMode, wifiMode)")
    options, args = parser.parse_args()
    if len(args) != 3:
        parser.error("invalid arguments")
        return 1
    if args[0] not in ('send', 'recv'):
        parser.error("invalid mode")
        return 1

    def _func(so, si):
        import select
        print(("si", si))
        print(("so", so))

        def getc(size, timeout=3):
            read_ready, _, _ = select.select([so], [], [], timeout)
            if read_ready:
                data = so.read(size)
            else:
                data = None
            print(("getc(", repr(data), ")"))
            return data

        def putc(data, timeout=3):
            _, write_ready, _ = select.select([], [si], [], timeout)
            if write_ready:
                si.write(data)
                si.flush()
                size = len(data)
            else:
                size = None
            print(("putc(", repr(data), repr(size), ")"))
            return size

        return (getc, putc)

    def _pipe(*command):
        pipe = subprocess.Popen(command, stdout=(subprocess.PIPE),
            stdin=(subprocess.PIPE))
        return (pipe.stdout, pipe.stdin)

    if args[0] == "recv":
        getc, putc = _func(*_pipe("sz", "--xmodem", args[2]))
        stream = open(args[1], "wb")
        xmodem = XMODEM(getc, putc, mode=(options.mode))
        status = xmodem.recv(stream, retry=8)
        stream.close()
    elif args[0] == "send":
        getc, putc = _func(*_pipe("rz", "--xmodem", args[2]))
        stream = open(args[1], "rb")
        xmodem = XMODEM(getc, putc, mode=(options.mode))
        sent = xmodem.send(stream, retry=8)
        stream.close()


if __name__ == "__main__":
    sys.exit(run())
