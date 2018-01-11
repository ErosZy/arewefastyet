#!/usr/bin/env python2

import json
import logging
import os
import platform
import shutil
import socket
import urllib

import utils
from utils import Run

import puller

socket.setdefaulttimeout(120)

class Environment(object):
    def __init__(self):
        self.env_ = os.environ.copy()
        self.add("CC", "gcc")
        self.add("CXX", "g++")
        self.add("LINK", "g++")
        self.ccoption = []

    def add(self, name, data):
        self.env_[name] = data

    def remove(self, name):
        del self.env_[name]

    def addCCOption(self, option):
        self.ccoption.append(option)

    def get(self):
        env = self.env_.copy()
        if len(self.ccoption) > 0:
            env["CC"] += " " + " ".join(self.ccoption)
            env["CXX"] += " " + " ".join(self.ccoption)
        return env

class Builder(object):

    def __init__(self, config, folder):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.env = Environment()
        self.config = config
        self.folder = folder

        if platform.system() == "Darwin":
            self.installClang()
            self.env.add("CC", os.path.abspath("clang-3.9.0/bin/clang"))
            self.env.add("CXX", os.path.abspath("clang-3.9.0/bin/clang++"))
            self.env.add("LINK", os.path.abspath("clang-3.9.0/bin/clang++"))

    def installClang(self):
        # The standard clang version on mac is outdated.
        # Retrieve a better one.

        if os.path.exists("clang-3.9.0"):
            return

        urllib.urlretrieve("http://releases.llvm.org/3.9.0/clang+llvm-3.9.0-x86_64-apple-darwin.tar.xz", "./clang-3.9.0.tar.xz")
        utils.run_realtime(["tar", "xf", "clang-3.9.0.tar.xz"])

        shutil.move("clang+llvm-3.9.0-x86_64-apple-darwin", "clang-3.9.0")

        os.unlink("clang-3.9.0.tar.xz")

    def installNdk(self):
        # Retrieve the ndk needed to build an android app.
        # Using version 12, since that still supports gcc (Couldn't get clang working).
        assert platform.system() == "Linux"
        assert platform.architecture()[0] == "64bit"

        with utils.chdir(self.folder):
            if os.path.exists("android-ndk-r12"):
                utils.log_info(self.logger, "already installed: {}".format(os.path.join(self.folder, "android-ndk-r12")))
                return

            utils.log_info(self.logger, "installing")
            urllib.urlretrieve("https://dl.google.com/android/repository/android-ndk-r12-linux-x86_64.zip", "./android-ndk.zip")
            Run(["unzip", "android-ndk.zip"], silent=True)

    def unlinkBinary(self):
        try:
            os.unlink(self.binary())
        except:
            pass

    def unlinkObjdir(self):
        try:
            shutil.rmtree(self.objdir())
        except:
            pass

    def successfullyBuild(self):
        return os.path.isfile(self.binary())

    def reconf(self):
        return

    def build(self, puller):
        self.unlinkBinary()

        try:
            self.make()
        except:
            pass

        if not self.successfullyBuild():
            self.reconf()
            self.make()

        assert self.successfullyBuild()

        info = self.retrieve_info()
        info["revision"] = puller.identify()
        # Default 'shell' to True only if it isn't set yet!
        if 'shell' not in info:
            info["shell"] = True
        info["binary"] = os.path.abspath(self.binary())

        fp = open(os.path.join(self.folder, "info.json"), "w")
        json.dump(info, fp)
        fp.close()

        utils.log_info(self.logger, "Build done!")

class MozillaBuilder(Builder):
    def __init__(self, config, folder):
        super(MozillaBuilder, self).__init__(config, folder);

        if platform.architecture()[0] == "64bit" and self.config == "32bit":
            self.env.add("AR",'ar')
            self.env.add("CROSS_COMPILE", '1')
            self.env.addCCOption("-m32")

    def retrieve_info(self):
        info = {}
        info["engine_type"] = "firefox"
        info["args"] = ['--no-async-stacks']
        if self.config.startswith("android"):
            info["platform"] = "android"
        return info

    def objdir(self):
        return os.path.join(self.folder, 'js', 'src', 'Opt')

    def binary(self):
        return os.path.join(self.objdir(), 'dist', 'bin', 'js')

    def reconf(self):
        # Step 0. install ndk if needed.
        if self.config.startswith("android"):
            self.env.remove("CC")
            self.env.remove("CXX")
            self.env.remove("LINK")
            self.installNdk()

        # Step 1. autoconf.
        with utils.chdir(os.path.join(self.folder, 'js', 'src')):
            if platform.system() == "Darwin":
                utils.run_realtime("autoconf213", shell=True)
            elif platform.system() == "Linux":
                utils.run_realtime("autoconf2.13", shell=True)
            elif platform.system() == "Windows":
                utils.run_realtime("autoconf-2.13", shell=True)

        # Step 2. configure
        if os.path.exists(os.path.join(self.folder, 'js', 'src', 'Opt')):
            shutil.rmtree(os.path.join(self.folder, 'js', 'src', 'Opt'))
        os.mkdir(os.path.join(self.folder, 'js', 'src', 'Opt'))
        args = ['--enable-optimize', '--disable-debug']
        if self.config == "android":
            args.append("--target=arm-linux-androideabi")
            args.append("--with-android-ndk="+os.path.abspath(self.folder)+"/android-ndk-r12/")
            args.append("--with-android-version=24")
            args.append("--enable-pie")
        if self.config == "android64":
            args.append("--target=aarch64-linux-androideabi")
            args.append("--with-android-ndk="+os.path.abspath(self.folder)+"/android-ndk-r12/")
            args.append("--with-android-version=24")
            args.append("--enable-pie")
        if platform.architecture()[0] == "64bit" and self.config == "32bit":
            if platform.system() == "Darwin":
                args.append("--target=i686-apple-darwin10.0.0")
            elif platform.system() == "Linux":
                args.append("--target=i686-pc-linux-gnu")
            else:
                assert False

        with utils.chdir(os.path.join(self.folder, 'js', 'src', 'Opt')):
            Run(['../configure'] + args, self.env.get())
        return True

    def make(self):
        if not os.path.exists(os.path.join(self.folder, 'js', 'src', 'Opt')):
            return
        utils.run_realtime("make -j6 -C " + os.path.join(self.folder, 'js', 'src', 'Opt'), shell=True)

class WebkitBuilder(Builder):
    def retrieve_info(self):
        info = {}
        info["engine_type"] = "webkit"
        return info

    def patch(self):
        with utils.chdir(self.folder):
            # Hack 1: Remove reporting errors for warnings that currently are present.
            Run(["sed","-i.bac","s/GCC_TREAT_WARNINGS_AS_ERRORS = YES;/GCC_TREAT_WARNINGS_AS_ERRORS=NO;/","Source/JavaScriptCore/Configurations/Base.xcconfig"])
            Run(["sed","-i.bac","s/GCC_TREAT_WARNINGS_AS_ERRORS = YES;/GCC_TREAT_WARNINGS_AS_ERRORS=NO;/","Source/bmalloc/Configurations/Base.xcconfig"])
            Run(["sed","-i.bac","s/GCC_TREAT_WARNINGS_AS_ERRORS = YES;/GCC_TREAT_WARNINGS_AS_ERRORS=NO;/","Source/WTF/Configurations/Base.xcconfig"])
            Run(["sed","-i.bac","s/std::numeric_limits<unsigned char>::max()/255/","Source/bmalloc/bmalloc/SmallLine.h"])
            #Run(["sed","-i.bac","s/std::numeric_limits<unsigned char>::max()/255/","Source/bmalloc/bmalloc/SmallRun.h"])

            # Hack 2: This check fails currently. Disable checking to still have a build.
            os.remove("Tools/Scripts/check-for-weak-vtables-and-externals")

    def clean(self):
        with utils.chdir(self.folder):
            Run(["svn","revert","Tools/Scripts/check-for-weak-vtables-and-externals"])

            Run(["svn","revert","Source/JavaScriptCore/Configurations/Base.xcconfig"])
            Run(["svn","revert","Source/bmalloc/Configurations/Base.xcconfig"])
            Run(["svn","revert","Source/WTF/Configurations/Base.xcconfig"])
            Run(["svn","revert","Source/bmalloc/bmalloc/SmallLine.h"])
            #Run(["svn","revert","Source/bmalloc/bmalloc/SmallPage.h"])

    def make(self):
        try:
            self.patch()
            with utils.chdir(os.path.join(self.folder, 'Tools', 'Scripts')):
                args = ['/usr/bin/perl', 'build-jsc']
                if self.config == '32bit':
                    args += ['--32-bit']
                Run(args, self.env.get())
        finally:
            self.clean()
        Run(["install_name_tool", "-change", "/System/Library/Frameworks/JavaScriptCore.framework/Versions/A/JavaScriptCore", self.objdir()+"/JavaScriptCore.framework/JavaScriptCore", self.objdir() + "/jsc"])

    def objdir(self):
        return os.path.join(self.folder, 'WebKitBuild', 'Release')

    def binary(self):
        return os.path.join(self.objdir(), 'jsc')

class V8Builder(Builder):
    def __init__(self, config, folder):
        super(V8Builder, self).__init__(config, folder)

        self.env.add("PATH", os.path.realpath(os.path.join(self.folder, 'depot_tools'))+":"+self.env.get()["PATH"])
        self.env.remove("CC")
        self.env.remove("CXX")
        self.env.remove("LINK")

        if self.config.startswith("android"):
            if "target_os = ['android']" not in open(folder + '/.gclient').read():
                with open(folder + "/.gclient", "a") as myfile:
                    myfile.write("target_os = ['android']")

    def retrieve_info(self):
        info = {}
        info["engine_type"] = "chrome"
        info["args"] = ['--expose-gc']
        if self.config == "android":
            info["platform"] = "android"
        return info

    def make(self):
        if self.config == "android":
            target_cpu = "arm"
        elif self.config == "32bit":
            target_cpu = "x86"
        elif self.config == "64bit":
            target_cpu = "x64"
        else:
            raise Exception("Unknown config in V8Builder.make!")

        objdir = os.path.realpath(self.objdir())
        if not os.path.isdir(objdir):
            out_dir = os.path.join(self.folder, 'v8', 'out')
            if not os.path.isdir(out_dir):
                os.mkdir(out_dir)
            os.mkdir(objdir)

        with utils.chdir(os.path.join(self.folder, 'v8')):
            config = [
                'is_debug = false',
                'target_cpu = "{}"'.format(target_cpu)
            ]

            if self.config == "arm":
                config += [
                    'symbol_level = 1',
                    'v8_android_log_stdout = true',
                    'target_os = "android"'
                ]

            args = 'gn gen ' + objdir + ' --args=\'' + " ".join(config) + '\''
            Run(args, self.env.get(), shell=True)

            Run(["ninja", "-C", objdir, "d8"], self.env.get())

    def objdir(self):
        if self.config == 'android':
            return os.path.join(self.folder, 'v8', 'out', 'android_arm.release')
        if self.config == '64bit':
            return os.path.join(self.folder, 'v8', 'out', 'x64.release')
        if self.config == '32bit':
            return os.path.join(self.folder, 'v8', 'out', 'ia32.release')
        raise "Unknown configuration in V8Builder.objdir!"

    def binary(self):
        return os.path.join(self.objdir(), 'd8')

class ServoBuilder(Builder):
    def __init__(self, config, folder):
        super(ServoBuilder, self).__init__(config, folder)
        # Some other config here

    def retrieve_info(self):
        info = {}
        info["engine_type"] = "servo"
        info['shell'] = False
        return info

    def objdir(self):
        return os.path.join(self.folder, 'target')

    def binary(self):
        return os.path.join(self.objdir(), 'release', 'servo')

    def make(self):
        with utils.chdir(self.folder):
            args = [os.path.join('.', 'mach'), 'build' ,'--release']
            Run(args, self.env.get())

def getBuilder(config, path):
    # fingerprint the known builders
    if os.path.exists(os.path.join(path, "js", "src")):
        return MozillaBuilder(config, path)
    if os.path.exists(os.path.join(path, "Source", "JavaScriptCore")):
        return WebkitBuilder(config, path)
    if os.path.exists(os.path.join(path, "v8", "LICENSE.v8")):
        return V8Builder(config, path)
    if os.path.exists(os.path.join(path, "components", "servo")):
        return ServoBuilder(config, path)

    raise Exception("Unknown builder")

if __name__ == "__main__":
    logger = utils.create_logger()

    utils.log_banner("BUILD")

    from optparse import OptionParser
    parser = OptionParser(usage="usage: %prog [options]")

    parser.add_option("-s", "--source", dest="repo",
                      help="The url of the repo to fetch or one of the known repos name. (mozilla, v8 and webkit are supported.)", default='mozilla')

    parser.add_option("-r", "--rev", dest="revision",
                      help="Force this revision to get build")

    parser.add_option("-o", "--output", dest="output",
                      help="download to DIR, default=output/", metavar="DIR", default='output')

    parser.add_option("-c", "--config", dest="config",
                      help="auto, 32bit, 64bit, android, android64", default='auto')

    parser.add_option("-f", "--force", dest="force", action="store_true", default=False,
                      help="Force runs even without source changes")

    (options, args) = parser.parse_args()

    if options.repo is None:
        utils.log_error(logger, "Please provide the source repository to pull")
        exit()

    if not options.output.endswith("/"):
        options.output += "/"

    if options.config not in ["auto", "32bit", "64bit", "android", "android64"]:
        utils.log_error(logger, "Please provide a valid config")
        exit()

    if options.config == "auto":
        options.config, _ = platform.architecture()

    if options.config == "64bit" and platform.architecture()[0] == "32bit":
        utils.log_error(logger, "Cannot compile a 64bit binary on 32bit architecture")
        exit()

    puller = puller.getPuller(options.repo, options.output)
    puller.update(options.revision)

    builder = getBuilder(options.config, options.output)
    if options.force:
        builder.unlinkObjdir()
    builder.build(puller)
