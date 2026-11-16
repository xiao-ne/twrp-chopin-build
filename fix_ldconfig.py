#!/usr/bin/env python3
"""删掉 boot.img ramdisk 里那个 0 字节的 linkerconfig/ld.config.txt。

TWRP (twrp-14.1) 这棵树打出来的 recovery ramdisk 里，linkerconfig/ld.config.txt
是 0 字节。动态链接器只要发现 /linkerconfig/ld.config.txt 存在，就拿它当完整的
namespace 配置；空文件 = 零个 namespace，连 libc.so 都解析不了。

这机器上两份能正常启动的 ramdisk（原厂、OrangeFox）都**没有**这个文件 —— 没有时
链接器回落到内置默认值，这才是正常状态。所以这里直接删掉，而不是填内容
（试过填 system/etc/ld.config.txt，仍然起不来）。

用法: fix_ldconfig.py <boot.img> <输出路径>   （可以两参数同一个路径，原地改）
"""
import gzip
import hashlib
import struct
import sys

TARGET = "linkerconfig/ld.config.txt"
TARGET_DIRS = {"linkerconfig", "linkerconfig/"}
PAD_BLOCK = 512


def read_entries(rd):
    entries = []
    pos = 0
    while pos + 110 <= len(rd):
        if rd[pos:pos + 6] != b"070701":
            break
        f = [int(rd[pos + 6 + 8 * i:pos + 6 + 8 * (i + 1)], 16) for i in range(13)]
        namesize, filesize = f[11], f[6]
        name = rd[pos + 110:pos + 110 + namesize - 1].decode("utf-8", "replace")
        body = (pos + 110 + namesize + 3) // 4 * 4
        entries.append({"fields": f, "name": name, "data": rd[body:body + filesize]})
        pos = (body + filesize + 3) // 4 * 4
        if name == "TRAILER!!!":
            break
    return entries


def write_entries(entries):
    out = bytearray()
    for e in entries:
        f = list(e["fields"])
        name = e["name"].encode()
        data = e["data"]
        f[6] = len(data)
        f[11] = len(name) + 1
        out += b"070701" + b"".join(b"%08X" % v for v in f)
        out += name + b"\0"
        out += b"\0" * ((4 - len(out) % 4) % 4)
        out += data
        out += b"\0" * ((4 - len(out) % 4) % 4)
    while len(out) % PAD_BLOCK:
        out += b"\0"
    return bytes(out)


def main():
    src_path, out_path = sys.argv[1], sys.argv[2]
    img = bytearray(open(src_path, "rb").read())
    total = len(img)

    page = struct.unpack_from("<I", img, 36)[0]
    hdrver = struct.unpack_from("<I", img, 40)[0]
    assert hdrver == 2, "only boot header v2 is handled"
    ks = struct.unpack_from("<I", img, 8)[0]
    rs = struct.unpack_from("<I", img, 16)[0]
    dtb_size = struct.unpack_from("<I", img, 1648)[0]

    koff = page
    roff = koff + (ks + page - 1) // page * page
    doff = roff + (rs + page - 1) // page * page
    kernel = bytes(img[koff:koff + ks])
    ramdisk = bytes(img[roff:roff + rs])
    dtb = bytes(img[doff:doff + dtb_size])

    rd = gzip.decompress(ramdisk)
    entries = read_entries(rd)

    names = {e["name"] for e in entries}
    if TARGET not in names:
        print("no %s in ramdisk - nothing to do" % TARGET)
        return 0

    kept = [e for e in entries if e["name"] != TARGET]
    # 目录里没东西了就把目录项也去掉
    if not any(e["name"].startswith("linkerconfig/") for e in kept):
        kept = [e for e in kept if e["name"] not in TARGET_DIRS]
    print("%s: removed (%d entries -> %d)" % (TARGET, len(entries), len(kept)))

    new_rd = write_entries(kept)
    new_gz = gzip.compress(new_rd, 9)
    print("ramdisk: %d unpacked, %d -> %d bytes gzip" % (len(new_rd), rs, len(new_gz)))

    header = bytearray(img[:page])
    struct.pack_into("<I", header, 16, len(new_gz))
    digest = hashlib.sha1()
    digest.update(kernel)
    digest.update(struct.pack("<I", len(kernel)))
    digest.update(new_gz)
    digest.update(struct.pack("<I", len(new_gz)))
    header[576:596] = digest.digest()
    assert len(header) == page, "header shrank: %d != %d" % (len(header), page)

    out = bytearray(header)
    out += kernel + b"\0" * ((page - len(kernel) % page) % page)
    out += new_gz + b"\0" * ((page - len(new_gz) % page) % page)
    out += dtb + b"\0" * ((page - len(dtb) % page) % page)
    if len(out) < total:
        out += b"\0" * (total - len(out))
    elif len(out) > total:
        print("ERROR: new image %d exceeds partition %d" % (len(out), total), file=sys.stderr)
        return 1

    open(out_path, "wb").write(bytes(out))
    print("written %s (%d bytes)" % (out_path, len(out)))
    print("sha256: %s" % hashlib.sha256(bytes(out)).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
