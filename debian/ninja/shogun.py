#!/usr/bin/python3.6
# Copyright (C) 2018 Mo Zhou <lumin@debian.org>
# Distribution Friendly Light-Weight Build for TensorFlow.
# MIT/Expat License.

'''
Shogun needs the bazel dumps from bazelQuery.sh .

For extra compiler definitions .e.g TENSORFLOW_USE_JEMALLOC please lookup
  tensorflow/core/platform/default/build_config.bzl
'''

from typing import *
import sys
import re
import os
import argparse
import json
from pprint import pprint
from ninja_syntax import Writer


def cyan(s: str) -> str:
    return f'\033[1;36m{s}\033[0;m'

def yellow(s: str) -> str:
    return f'\033[1;33m{s}\033[0;m'


def filteroutExternal(sourcelist: List[str]) -> List[str]:
    '''
    Filter out external dependencies from bazel dependency dump
    '''
    external = set()
    ret = []
    for src in sourcelist:
        x = re.match('^@(\w*).*', src)
        if x is None:
            ret.append(src)
        else:
            external.update(x.groups())
    print(cyan('Required Depends:'), json.dumps(list(external), indent=4))
    return ret


def mangleBazel(sourcelist: List[str]) -> List[str]:
    '''
    mangling source file path
    '''
    ret = []
    for x in sourcelist:
        x = re.sub('^//', '', x)
        x = re.sub(':', '/', x)
        ret.append(x)
    return ret


def eGrep(pat: str, sourcelist: List[str]) -> (List[str], List[str]):
    '''
    Just like grep -E
    '''
    match, unmatch = [], []
    for item in sourcelist:
        if re.match(pat, item):
            match.append(item)
        else:
            unmatch.append(item)
    return match, unmatch


def ninjaCommonHeader(cursor: Writer, ag: Any) -> None:
    '''
    Writes a common header to the ninja file. ag is parsed arguments.
    '''
    cursor.comment(f'automatically generated by {__file__}')
    cursor.newline()
    cursor.variable('CXX', 'g++')
    cursor.variable('CPPFLAGS', '')
    cursor.variable('CXXFLAGS', '-w -std=c++14 -O2 -fPIC -gsplit-dwarf -pthread')
    cursor.variable('LDFLAGS', '')
    cursor.variable('INCLUDES', '-I. -I./debian/embedded/eigen/ -I./third_party/eigen3/'
            + ' -I/usr/include/gemmlowp -I/usr/include/jsoncpp -I/usr/include/llvm-c-6.0'
            + ' -I/usr/include/llvm-6.0 -Ithird_party/toolchains/gpus/cuda/')
    cursor.variable('LIBS', '-lpthread -lprotobuf -lnsync -lnsync_cpp -ldouble-conversion'
	+ ' -ldl -lm -lz -lre2 -ljpeg -lpng -lsqlite3 -llmdb -lsnappy -lgif -lLLVM-6.0')
    cursor.variable('PROTO_TEXT_ELF', f'{ag.B}/proto_text')
    cursor.newline()
    cursor.rule('PROTOC', f'protoc $in --cpp_out {ag.B}')
    cursor.rule('PROTOC_GRPC', f'protoc --grpc_out {ag.B} --cpp_out {ag.B} --plugin protoc-gen-grpc=/usr/bin/grpc_cpp_plugin $in')
    cursor.rule('PROTO_TEXT', f'$PROTO_TEXT_ELF {ag.B}/tensorflow/core tensorflow/core tensorflow/tools/proto_text/placeholder.txt $in')
    cursor.rule('GEN_VERSION_INFO', f'bash {ag.B}/tensorflow/tools/git/gen_git_source.sh $out')
    cursor.rule('CXX_OBJ', f'g++ $CXXFLAGS $INCLUDES -c $in -o $out')
    cursor.rule('CXX_EXEC', f'g++ $CXXFLAGS $INCLUDES $LDFLAGS $LIBS $in -o $out')
    cursor.rule('CXX_SHLIB', f'g++ -shared -fPIC $CXXFLAGS $INCLUDES $LDFLAGS $LIBS $in -o $out')
    cursor.rule('STATIC', f'ar rcs $out $in')
    cursor.comment('CXX_CC_OP_EXEC: $in should be e.g. tensorflow/core/ops/array_ops.cc')
    cursor.variable('CC_OP_INC_AND_LIB', '-Idebian/embedded/eigen -I. -L. -ltensorflow_framework -lpthread -lprotobuf -ldl')
    cursor.rule('CXX_CC_OP_EXEC', '$CXX $CPPFLAGS $CXXFLAGS'
            + ' tensorflow/core/framework/op_gen_lib.cc'
            + ' tensorflow/cc/framework/cc_op_gen.cc'
            + ' tensorflow/cc/framework/cc_op_gen_main.cc'
            + ' $in $CC_OP_INC_AND_LIB -o $out')
    cursor.rule('CXX_CC_OP_GEN', f'LD_LIBRARY_PATH={ag.B} ./$in $out $cc_op_gen_internal' \
            + ' tensorflow/core/api_def/base_api')
    cursor.rule('COPY', f'cp $in $out')
    cursor.newline()


def ninjaProto(cur, protolist: List[str]) -> List[str]:
    '''
    write ninja rules for the protofiles. cur is ninja writer
    '''
    protos, cclist, hdrlist = [], [], []
    for proto in protolist:
        # proto is a protobuf-related file.
        if proto.endswith('.proto'):
            protos.append(proto)
            cclist.append(re.sub('.proto$', '.pb.cc', proto))
            hdrlist.append(re.sub('.proto$', '.pb.h', proto))
        elif proto.endswith('.pb.cc'):
            protos.append(re.sub('.pb.cc$', '.proto', proto))
            cclist.append(proto)
            hdrlist.append(re.sub('.pb.cc$', '.pb.h', proto))
        elif proto.endswith('.pb.h'):
            protos.append(re.sub('.pb.h$', '.proto', proto))
            cclist.append(re.sub('.pb.h$', '.pb.cc', proto))
            hdrlist.append(proto)
        else:
            raise SyntaxError(f'what is {proto}?')
    for p in list(set(protos)):
        output = [re.sub('.proto$', '.pb.cc', p),
                re.sub('.proto$', '.pb.h', p)]
        cur.build(output, 'PROTOC', inputs=p)
    return list(set(protos)), list(set(cclist)), list(set(hdrlist))


def ninjaProtoText(cur, protolist: List[str]) -> List[str]:
    '''
    write ninja rules for to proto_text files. cur is ninja writer
    '''
    protos, cclist, hdrlist = [], [], []
    for proto in protolist:
        # proto is a proto_text-related file
        if proto.endswith('.proto'):
            protos.append(proto)
            cclist.append(re.sub('.proto$', '.pb_text.cc', proto))
            hdrlist.append(re.sub('.proto$', '.pb_text.h', proto))
            hdrlist.append(re.sub('.proto$', '.pb_text-impl.h', proto))
        elif proto.endswith('.pb_text.cc'):
            protos.append(re.sub('.pb_text.cc$', '.proto', proto))
            cclist.append(proto)
            hdrlist.append(re.sub('.pb_text.cc$', '.pb_text.h', proto))
            hdrlist.append(re.sub('.pb_text.cc$', '.pb_text-impl.h', proto))
        elif proto.endswith('.pb_text.h'):
            protos.append(re.sub('.pb_text.h$', '.proto', proto))
            cclist.append(re.sub('.pb_text.h$', '.pb_text.cc', proto))
            hdrlist.append(proto)
            hdrlist.append(re.sub('.pb_text.h$', '.pb_text-impl.h', proto))
        elif proto.endswith('.pb_text-impl.h'):
            protos.append(re.sub('.pb_text-impl.h$', '.proto', proto))
            cclist.append(re.sub('.pb_text-impl.h$', '.pb_text.cc', proto))
            hdrlist.append(re.sub('.pb_text-impl.h$', '.pb_text.h', proto))
            hdrlist.append(proto)
        else:
            raise SyntaxError(f'what is {proto}?')
    for p in list(set(protos)):
        output = [re.sub('.proto$', '.pb_text.cc', p),
                re.sub('.proto$', '.pb_text.h', p),
                re.sub('.proto$', '.pb_text-impl.h', p)]
        cur.build(output, 'PROTO_TEXT', inputs=p)
    return list(set(protos)), list(set(cclist)), list(set(hdrlist))


def ninjaCXXOBJ(cur, cclist: List[str]) -> List[str]:
    '''
    write ninja rules for building .cc files into object files
    '''
    objs = []
    for cc in cclist:
        output = re.sub('.cc$', '.o', cc)
        objs.append(cur.build(output, 'CXX_OBJ', inputs=cc)[0])
    return objs


def shogunProtoText(argv):
    '''
    Build proto_text
    '''
    ag = argparse.ArgumentParser()
    ag.add_argument('-i', help='list of source files', type=str, required=True)
    ag.add_argument('-g', help='list of generated files', type=str, required=True)
    ag.add_argument('-o', help='where to write the ninja file', type=str, default='proto_text.ninja')
    ag.add_argument('-B', help='build directory', type=str, default='.')
    ag = ag.parse_args(argv)

    srclist = [l.strip() for l in open(ag.i, 'r').readlines()]
    genlist = [l.strip() for l in open(ag.g, 'r').readlines()]
    srclist, genlist = filteroutExternal(srclist), filteroutExternal(genlist)
    srclist, genlist = mangleBazel(srclist), mangleBazel(genlist)

    # Instantiate ninja writer
    cursor = Writer(open(ag.o, 'w'))
    ninjaCommonHeader(cursor, ag)

    # generate .pb.cc and .pb.h
    srcproto, srclist = eGrep('.*.proto$', srclist)
    genpbh, genlist = eGrep('.*.pb.h', genlist)
    genpbcc, genlist = eGrep('.*.pb.cc', genlist)
    protolist, pbcclist, pbhlist = ninjaProto(cursor, genpbh + genpbcc)
    proto_diff = set(srcproto).difference(set(protolist))
    if len(proto_diff) > 0:
        print('Warning: resulting proto lists different!', proto_diff)

    # ignore .h files and third_party, and windows source
    srchdrs, srclist = eGrep('.*.h$', srclist)
    _, srclist = eGrep('^third_party', srclist)
    _, srclist = eGrep('.*windows/env_time.cc$', srclist)

    # compile .cc source
    cclist, srclist = eGrep('.*.cc', srclist)
    proto_text_objs = ninjaCXXOBJ(cursor, cclist + pbcclist)

    # link the final executable
    cursor.build('proto_text', 'CXX_EXEC', inputs=proto_text_objs)

    # fflush
    print(yellow('Unprocessed src files:'), json.dumps(srclist, indent=4))
    print(yellow('Unprocessed gen files:'), json.dumps(genlist, indent=4))
    cursor.close()


def shogunTFCoreProto(argv):
    '''
    Build tf_core_proto.a
    '''
    ag = argparse.ArgumentParser()
    ag.add_argument('-i', help='list of source files', type=str, required=True)
    ag.add_argument('-g', help='list of generated files', type=str, required=True)
    ag.add_argument('-o', help='where to write the ninja file', type=str, default='tf_core_proto.ninja')
    ag.add_argument('-B', help='build directory', type=str, default='.')
    ag = ag.parse_args(argv)

    srclist = [l.strip() for l in open(ag.i, 'r').readlines()]
    genlist = [l.strip() for l in open(ag.g, 'r').readlines()]
    srclist, genlist = filteroutExternal(srclist), filteroutExternal(genlist)
    srclist, genlist = mangleBazel(srclist), mangleBazel(genlist)

    # Instantiate ninja writer
    cursor = Writer(open(ag.o, 'w'))
    ninjaCommonHeader(cursor, ag)

    # generate .pb.cc and .pb.h
    srcproto, srclist = eGrep('.*.proto$', srclist)
    genpbh, genlist = eGrep('.*.pb.h', genlist)
    genpbcc, genlist = eGrep('.*.pb.cc', genlist)
    protolist, pbcclist, pbhlist = ninjaProto(cursor, genpbh + genpbcc)
    proto_diff = set(srcproto).difference(set(protolist))
    if len(proto_diff) > 0:
        print(yellow('Warning: resulting proto lists different!'), proto_diff)

    # generate .pb_text.cc .pb_text.h .pb_test-impl.h
    genpbth, genlist = eGrep('.*.pb_text.h', genlist)
    genpbtimplh, genlist = eGrep('.*.pb_text-impl.h', genlist)
    genpbtcc, genlist = eGrep('.*.pb_text.cc', genlist)
    pbtprotolist, pbtcclist, pbthlist = ninjaProtoText(cursor,
            genpbth + genpbtimplh + genpbtcc)
    pbtproto_diff = set(srcproto).difference(set(pbtprotolist))
    if len(proto_diff) > 0:
        print(yellow('Warning: resulting proto lists different!'), proto_diff)

    # compile .cc source
    tf_core_pb_obj = ninjaCXXOBJ(cursor, genpbcc + genpbtcc)

    # link the final executable
    cursor.build('tf_core_proto.a', 'STATIC', inputs=tf_core_pb_obj)

    ## fflush
    #print(yellow('Unprocessed src files:'), srclist) # Ignore
    print(yellow('Unprocessed gen files:'), json.dumps(genlist, indent=4))
    cursor.close()


def shogunTFFrame(argv):
    '''
    Build libtensorflow_framework.so
    '''
    ag = argparse.ArgumentParser()
    ag.add_argument('-i', help='list of source files', type=str, required=True)
    ag.add_argument('-g', help='list of generated files', type=str, required=True)
    ag.add_argument('-o', help='where to write the ninja file', type=str, default='libtensorflow_framework.ninja')
    ag.add_argument('-B', help='build directory', type=str, default='.')
    ag = ag.parse_args(argv)

    srclist = filteroutExternal([l.strip() for l in open(ag.i, 'r').readlines()])
    genlist = filteroutExternal([l.strip() for l in open(ag.g, 'r').readlines()])
    srclist, genlist = mangleBazel(srclist), mangleBazel(genlist)

    # Instantiate ninja writer
    cursor = Writer(open(ag.o, 'w'))
    ninjaCommonHeader(cursor, ag)

    # generate .pb.cc and .pb.h
    srcproto, srclist = eGrep('.*.proto$', srclist)
    genpbh, genlist = eGrep('.*.pb.h', genlist)
    genpbcc, genlist = eGrep('.*.pb.cc', genlist)
    protolist, pbcclist, pbhlist = ninjaProto(cursor, genpbh + genpbcc)
    proto_diff = set(srcproto).difference(set(protolist))
    if len(proto_diff) > 0:
        print(yellow('Warning: resulting proto lists different!'), proto_diff)

    # generate .pb_text.cc .pb_text.h .pb_test-impl.h
    genpbth, genlist = eGrep('.*.pb_text.h', genlist)
    genpbtimplh, genlist = eGrep('.*.pb_text-impl.h', genlist)
    genpbtcc, genlist = eGrep('.*.pb_text.cc', genlist)
    pbtprotolist, pbtcclist, pbthlist = ninjaProtoText(cursor,
            genpbth + genpbtimplh + genpbtcc)
    pbtproto_diff = set(srcproto).difference(set(pbtprotolist))
    if len(proto_diff) > 0:
        print(yellow('Warning: resulting proto lists different!'), proto_diff)

    # generate version info, the last bit in list of generated files
    print(yellow('Unprocessed generated files:'), genlist)
    assert(len(genlist) == 1)
    srclist.extend(cursor.build(genlist[0], 'GEN_VERSION_INFO'))

    # ignore .h files and third_party, and windows source
    _, srclist = eGrep('.*.h$', srclist)
    _, srclist = eGrep('^third_party', srclist)
    _, srclist = eGrep('.*windows/env_time.cc$', srclist)
    _, srclist = eGrep('.*platform/windows.*', srclist)

    # compile .cc source
    cclist, srclist = eGrep('.*.cc', srclist)
    tf_framework_objs = ninjaCXXOBJ(cursor, cclist + pbcclist + pbtcclist)

    # link the final executable
    cursor.build('libtensorflow_framework.so', 'CXX_SHLIB', inputs=tf_framework_objs,
            variables={'LIBS': '-lfarmhash -lhighwayhash -lsnappy -lgif'
            + ' -ldouble-conversion -lz -lprotobuf -ljpeg -lnsync -lnsync_cpp'
            + ' -lpthread'})
    # XXX: jemalloc

    ## fflush
    print(yellow('Unprocessed src files:'), json.dumps(srclist, indent=4))
    print(yellow('Unprocessed gen files:'), json.dumps(genlist, indent=4))
    cursor.close()


def shogunTFLibAndroid(argv):
    '''
    Build libtensorflow_android.so
    '''
    ag = argparse.ArgumentParser()
    ag.add_argument('-i', help='list of source files', type=str, required=True)
    ag.add_argument('-g', help='list of generated files', type=str, required=True)
    ag.add_argument('-o', help='where to write the ninja file', type=str, default='libtensorflow_android.ninja')
    ag.add_argument('-B', help='build directory', type=str, default='.')
    ag = ag.parse_args(argv)

    srclist = filteroutExternal([l.strip() for l in open(ag.i, 'r').readlines()])
    genlist = filteroutExternal([l.strip() for l in open(ag.g, 'r').readlines()])
    srclist, genlist = mangleBazel(srclist), mangleBazel(genlist)

    # Instantiate ninja writer
    cursor = Writer(open(ag.o, 'w'))
    ninjaCommonHeader(cursor, ag)

    # generate .pb.cc and .pb.h
    srcproto, srclist = eGrep('.*.proto$', srclist)
    genpbh, genlist = eGrep('.*.pb.h', genlist)
    genpbcc, genlist = eGrep('.*.pb.cc', genlist)
    protolist, pbcclist, pbhlist = ninjaProto(cursor, genpbh + genpbcc)
    proto_diff = set(srcproto).difference(set(protolist))
    if len(proto_diff) > 0:
        print(yellow('Warning: resulting proto lists different!'), proto_diff)

    # generate .pb_text.cc .pb_text.h .pb_test-impl.h
    genpbth, genlist = eGrep('.*.pb_text.h', genlist)
    genpbtimplh, genlist = eGrep('.*.pb_text-impl.h', genlist)
    genpbtcc, genlist = eGrep('.*.pb_text.cc', genlist)
    pbtprotolist, pbtcclist, pbthlist = ninjaProtoText(cursor,
            genpbth + genpbtimplh + genpbtcc)
    pbtproto_diff = set(srcproto).difference(set(pbtprotolist))
    if len(proto_diff) > 0:
        print(yellow('Warning: resulting proto lists different!'), proto_diff)

    # ignore .h files and third_party, and windows source
    _, srclist = eGrep('.*.h$', srclist)
    _, srclist = eGrep('^third_party', srclist)
    _, srclist = eGrep('.*windows/env_time.cc$', srclist)
    _, srclist = eGrep('.*platform/windows.*', srclist)
    _, srclist = eGrep('.*stream_executor.*', srclist) # due to CPU-only

    # compile .cc source
    cclist, srclist = eGrep('.*.cc', srclist)
    tf_android_objs = ninjaCXXOBJ(cursor, cclist + pbcclist + pbtcclist)

    # link the final executable
    cursor.build('libtensorflow_android.so', 'CXX_SHLIB', inputs=tf_android_objs,
            variables={'LIBS': '-lpthread -lprotobuf -lnsync -lnsync_cpp'
                + ' -ldouble-conversion'})

    ## fflush
    print(yellow('Unprocessed src files:'), json.dump(srclist, indent=4))
    print(yellow('Unprocessed gen files:'), json.dump(genlist, indent=4))
    cursor.close()


def shogunCCOP(argv):
    '''
    Generate tensorflow/cc/ops/*.cc and *.h
    '''
    ag = argparse.ArgumentParser()
    ag.add_argument('-i', help='list of source files', type=str, required=True)
    ag.add_argument('-g', help='list of generated files', type=str, required=True)
    ag.add_argument('-o', help='where to write the ninja file', type=str, default='ccop.ninja')
    ag.add_argument('-B', help='build directory', type=str, default='.')
    ag = ag.parse_args(argv)

    genlist = filteroutExternal([l.strip() for l in open(ag.g, 'r').readlines()])
    genlist = mangleBazel(genlist)

    # Instantiate ninja writer
    cursor = Writer(open(ag.o, 'w'))
    ninjaCommonHeader(cursor, ag)

    # filter unrelated files
    _, genlist = eGrep('.*.pb.h', genlist)
    _, genlist = eGrep('.*.pb.cc', genlist)
    _, genlist = eGrep('.*.pb_text.h', genlist)
    _, genlist = eGrep('.*.pb_text-impl.h', genlist)
    _, genlist = eGrep('.*.pb_text.cc', genlist)

    # cc_op_gen
    cursor.build('tensorflow/core/ops/user_ops.cc', 'COPY', inputs='tensorflow/core/user_ops/fact.cc')
    ccoplist, genlist = eGrep('.*/cc/ops/.*.cc', genlist)
    ccophdrs, genlist = eGrep('.*/cc/ops/.*.h', genlist)
    for ccop in (x for x in ccoplist if 'internal' not in x):
        coreop = re.sub('/cc/', '/core/', ccop)
        opname = os.path.basename(ccop).split('.')[0]
        cursor.build(f'{opname}_gen_cc', 'CXX_CC_OP_EXEC', inputs=coreop)
        cursor.build([ccop.replace('.cc', '.h'), ccop], 'CXX_CC_OP_GEN', inputs=f'./{opname}_gen_cc',
                variables={'cc_op_gen_internal': '0' if opname != 'sendrecv_ops' else '1'},
                implicit_outputs=[ccop.replace('.cc', '_internal.h'), ccop.replace('.cc', '_internal.cc')])

    ## fflush
    print(yellow('Unprocessed gen files:'), json.dumps(genlist, indent=4))
    cursor.close()


def shogunTFLib(argv):
    '''
    Build libtensorflow.so
    '''
    ag = argparse.ArgumentParser()
    ag.add_argument('-i', help='list of source files', type=str, required=True)
    ag.add_argument('-g', help='list of generated files', type=str, required=True)
    ag.add_argument('-o', help='where to write the ninja file', type=str,
            default='libtensorflow.ninja')
    ag.add_argument('-B', help='build directory', type=str, default='.')
    ag = ag.parse_args(argv)

    srclist = filteroutExternal([l.strip() for l in open(ag.i, 'r').readlines()])
    genlist = filteroutExternal([l.strip() for l in open(ag.g, 'r').readlines()])
    srclist, genlist = mangleBazel(srclist), mangleBazel(genlist)

    # Instantiate ninja writer
    cursor = Writer(open(ag.o, 'w'))
    ninjaCommonHeader(cursor, ag)

    # generate .pb.cc and .pb.h
    srcproto, srclist = eGrep('.*.proto$', srclist)
    genpbh, genlist = eGrep('.*.pb.h', genlist)
    genpbcc, genlist = eGrep('.*.pb.cc', genlist)
    protolist, pbcclist, pbhlist = ninjaProto(cursor,
            [x for x in (genpbh + genpbcc) if '.grpc.pb' not in x])
    proto_diff = set(srcproto).difference(set(protolist))
    if len(proto_diff) > 0:
        print(yellow('Warning: resulting proto lists different!'), proto_diff)

    # generate .pb_text.cc .pb_text.h .pb_test-impl.h
    genpbth, genlist = eGrep('.*.pb_text.h', genlist)
    genpbtimplh, genlist = eGrep('.*.pb_text-impl.h', genlist)
    genpbtcc, genlist = eGrep('.*.pb_text.cc', genlist)
    pbtprotolist, pbtcclist, pbthlist = ninjaProtoText(cursor,
            genpbth + genpbtimplh + genpbtcc)
    pbtproto_diff = set(srcproto).difference(set(pbtprotolist))
    if len(proto_diff) > 0:
        print(yellow('Warning: resulting proto lists different!'), proto_diff)

    # XXX: temporary workaround for //tensorflow/core/debug:debug_service.grpc.pb.cc
    cursor.build([f'{ag.B}/tensorflow/core/debug/debug_service.grpc.pb.cc',
        f'{ag.B}/tensorflow/core/debug/debug_service.grpc.pb.h'],
        'PROTOC_GRPC', inputs='tensorflow/core/debug/debug_service.proto')
    pbcclist.append(f'{ag.B}/tensorflow/core/debug/debug_service.grpc.pb.cc')

    # ignore .h files and third_party, and windows source
    _, srclist = eGrep('.*.h$', srclist)
    _, srclist = eGrep('^third_party', srclist)
    _, srclist = eGrep('.*windows/env_time.cc$', srclist)
    _, srclist = eGrep('.*platform/windows.*', srclist)
    _, srclist = eGrep('.*.cu.cc$', srclist) # no CUDA file for CPU-only build
    _, srclist = eGrep('.*.pbtxt$', srclist) # no need to process

    # cc_op_gen
    ccoplist, genlist = eGrep('.*/cc/ops/.*.cc', genlist)
    ccophdrs, genlist = eGrep('.*/cc/ops/.*.h', genlist)

    # compile .cc source
    cclist, srclist = eGrep('.*.cc', srclist)
    tf_android_objs = ninjaCXXOBJ(cursor, cclist + pbcclist + pbtcclist + ccoplist)

    # link the final executable
    cursor.build('libtensorflow.so', 'CXX_SHLIB', inputs=tf_android_objs,
            variables={'LIBS': '-lpthread -lprotobuf -lnsync -lnsync_cpp'
                + ' -ldouble-conversion -lz -lpng -lgif -lhighwayhash'
                + ' -ljpeg -lfarmhash -ljsoncpp -lsqlite3 -lre2 -lcurl'
                + ' -llmdb -lsnappy'})
    # FIXME: jemalloc, mkl-dnn, grpc, xsmm

    ## fflush
    print(yellow('Unprocessed src files:'), json.dumps(srclist, indent=4))
    print(yellow('Unprocessed gen files:'), json.dumps(genlist, indent=4))
    cursor.close()


if __name__ == '__main__':

    # A graceful argparse implementation with argparse subparser requries
    # much more boring code than I would like to write.
    try:
        sys.argv[1]
    except IndexError as e:
        print(e, 'you must specify one of the following a subcommand:')
        print([k for (k, v) in locals().items() if k.startswith('shogun')])
        exit(1)

    # Targets sorted in dependency order.
    if sys.argv[1] == 'ProtoText':
        shogunProtoText(sys.argv[2:])
    elif sys.argv[1] == 'TFCoreProto':
        shogunTFCoreProto(sys.argv[2:])
    elif sys.argv[1] == 'TFFrame':
        shogunTFFrame(sys.argv[2:])
    elif sys.argv[1] == 'TFLibAndroid':
        shogunTFLibAndroid(sys.argv[2:])
    elif sys.argv[1] == 'CCOP':
        shogunCCOP(sys.argv[2:])
    elif sys.argv[1] == 'TFLib':
        shogunTFLib(sys.argv[2:])
    else:
        raise NotImplementedError(sys.argv[1:])
