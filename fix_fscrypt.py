#!/usr/bin/env python3
import os

os.chdir(os.environ.get('WORKDIR', os.getcwd()))

for fname in ['bootable/recovery/libtar/append.c', 'bootable/recovery/libtar/block.c']:
    if not os.path.exists(fname):
        print(f'Skip {fname}')
        continue
    with open(fname) as f:
        lines = f.readlines()
    skip_until = 0
    result = []
    for line in lines:
        if skip_until > 0:
            skip_until += line.count('{') - line.count('}')
            if skip_until <= 0:
                skip_until = 0
            continue
        if any(fn in line for fn in ['fscrypt_policy_get_struct', 'fscrypt_policy_size',
                'get_policy_size', 'get_policy_descriptor',
                'lookup_ref_key(t->th_buf.fep']):
            skip_until = line.count('{') - line.count('}')
            if skip_until <= 0:
                skip_until = 0
            continue
        result.append(line)
    with open(fname, 'w') as f:
        f.writelines(result)
    print(f'Fixed {fname}')

try:
    with open('bootable/recovery/libtar/libtar.h') as f:
        c = f.read()
    c = c.replace('fscrypt_policy  *fep;', 'struct fscrypt_policy_v1 *fep;')
    with open('bootable/recovery/libtar/libtar.h', 'w') as f:
        f.write(c)
    print('Fixed libtar.h')
except:
    pass
