"""Common OSTree functions

Helper functions for commonly used OSTree functions.
"""

import logging
import os

import gi
gi.require_version("OSTree", "1.0")
from gi.repository import Gio, GLib, OSTree

from tcbuilder.errors import TorizonCoreBuilderError

log = logging.getLogger("torizon." + __name__)

OSTREE_BASE_REF = "base"

# Whiteout defines match what Containers are using:
# https://github.com/opencontainers/image-spec/blob/v1.0.1/layer.md#whiteouts
# this is from src/libostree/ostree-repo-checkout.c
OSTREE_WHITEOUT_PREFIX = ".wh."
OSTREE_OPAQUE_WHITEOUT_NAME = ".wh..wh..opq"

def open_ostree(ostree_dir):
    repo = OSTree.Repo.new(Gio.File.new_for_path(ostree_dir))
    if not repo.open(None):
        raise TorizonCoreBuilderError("Opening the archive OSTree repository failed.")
    return repo

def create_ostree(ostree_dir, mode:OSTree.RepoMode = OSTree.RepoMode.ARCHIVE_Z2):
    repo = OSTree.Repo.new(Gio.File.new_for_path(ostree_dir))
    repo.create(mode, None)
    return repo

def load_sysroot(sysroot_dir):
    sysroot = OSTree.Sysroot.new(Gio.File.new_for_path(sysroot_dir))
    sysroot.load()
    return sysroot

def get_deployment_info_from_sysroot(sysroot):
    # Get commit csum and kernel arguments from the currenty sysroot

    # There is a single deployment in our OSTree sysroots
    deployment = sysroot.get_deployments()[0]

    # Get the origin refspec
    #refhash = deployment.get_origin().get_string("origin", "refspec")

    bootparser = deployment.get_bootconfig()
    kargs = bootparser.get('options')
    csum = deployment.get_csum()
    sysroot.unload()

    return csum, kargs


def get_metadata_from_checksum(repo, csum):
    result, commitvar, _state = repo.load_commit(csum)
    if not result:
        raise TorizonCoreBuilderError(f"Error loading commit {csum}.")

    # commitvar is GLib.Variant, use unpack to get a Python dictionary
    commit = commitvar.unpack()

    # Unpack commit object, see OSTree src/libostree/ostree-repo-commit.c
    metadata, _parent, _, subject, body, _time, _content_csum, _metadata_csum = commit

    return metadata, subject, body

def get_metadata_from_ref(repo, ref):
    result, _, csum = repo.read_commit(ref)
    if not result:
        raise TorizonCoreBuilderError(f"Error loading commit {ref}.")

    return get_metadata_from_checksum(repo, csum)


def pull_remote_ref(repo, uri, ref, remote=None, progress=None):
    options = GLib.Variant("a{sv}", {
        "gpg-verify": GLib.Variant("b", False)
    })

    log.debug(f"Pulling remote {uri} reference {ref}")

    if not repo.remote_add("origin", remote, options=options):
        raise TorizonCoreBuilderError(f"Error adding remote {remote}.")

    # ostree --repo=toradex-os-tree pull origin torizon/torizon-core-docker --depth=0

    options = GLib.Variant("a{sv}", {
        "refs": GLib.Variant.new_strv([ref]),
        "depth": GLib.Variant("i", 0),
        "override-remote-name": GLib.Variant('s', remote),
    })

    if progress is not None:
        asyncprogress = OSTree.AsyncProgress.new()
        asyncprogress.connect("changed", progress)
    else:
        asyncprogress = None

    if not repo.pull_with_options("origin", options, progress=asyncprogress):
        raise TorizonCoreBuilderError("Error pulling contents from local repository.")

def pull_local_ref(repo, repopath, csum, remote=None):
    """ fetches reference from local repository

        args:

            repo(OSTree.Repo) - repo object
            repopath(str) - absolute path of local repository to pull from
            ref(str) - remote reference to pull
            remote = remote name used in refspec

        raises:
            Exception - for failure to perform operations
    """
    log.debug(f"Pulling from local repository {repopath} commit checksum {csum}")

    # ostree --repo=toradex-os-tree pull-local --remote=${branch} ${repopath} ${ref} --depth=0
    options = GLib.Variant("a{sv}", {
        "refs": GLib.Variant.new_strv([csum]),
        "depth": GLib.Variant("i", 0),
        "override-remote-name": GLib.Variant('s', remote),
    })

    if not repo.pull_with_options("file://" + repopath, options):
        raise TorizonCoreBuilderError(f"Error pulling contents from local repository {repopath}.")

    # Note: In theory we can do this with two options in one go, but that seems
    # to validate ref-bindings... (has probably something to do with Collection IDs etc..)
    #"refs": GLib.Variant.new_strv(["base"]),
    #"override-commit-ids": GLib.Variant.new_strv([ref]),
    repo.set_collection_ref_immediate(OSTree.CollectionRef.new(None, OSTREE_BASE_REF), csum)

def _convert_gio_file_type(gio_file_type):
    if gio_file_type == Gio.FileType.DIRECTORY:
        return 'directory'
    elif gio_file_type == Gio.FileType.MOUNTABLE:
        return 'mountable'
    elif gio_file_type == Gio.FileType.REGULAR:
        return 'regular'
    elif gio_file_type == Gio.FileType.SHORTCUT:
        return 'shortcut'
    elif gio_file_type == Gio.FileType.SPECIAL:
        return 'special'
    elif gio_file_type == Gio.FileType.SYMBOLIC_LINK:
        return 'symbolic_link'
    elif gio_file_type == Gio.FileType.UNKNOWN:
        return 'unknown'
    else:
        raise TorizonCoreBuilderError(f"Unknown gio filetype {gio_file_type}")

def check_existance(repo, commit, path, name):
    dir_contents = []
    dir_contents = ls(repo, path, commit)
    return any(content for content in dir_contents if content["name"] == name)

def ls(repo, path, commit):
    """ return a list of files and directories in a ostree repo under path

        args:
            repo(OSTree.Repo) - repo object
            path(str) - absolute path which we want to enumerate
            commit(str) - the ostree commit hash or name

        return:
            file_list(list) - list of files and directories under path

        raises:
            TorizonCoreBuilderError - if commit does not exist
    """
    # Make sure we don't end the path with / because this confuses ostree
    path = os.path.realpath(path)
    ret, root, _commit = repo.read_commit(commit)
    if not ret:
        raise TorizonCoreBuilderError(f"Error couldn't reat commit: {commit}")

    sub_path = root.resolve_relative_path(path)

    file_list = sub_path.enumerate_children(
        "*", Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, None)

    return list(map(lambda f: {"name": f.get_name(),
                               "type": _convert_gio_file_type(f.get_file_type())
                               }, file_list))

def get_kernel_version(repo, commit):
    """ return the kernel version used in the commit

        args:
            repo(OSTree.Repo) - repo object
            commit(str) - the ostree commit hash or name

        return:
            version(str) - The kernel version used in this OSTree commit
    """

    module_files = ls(repo, "/usr/lib/modules", commit)
    module_dirs = filter(lambda file: file["type"] == "directory",
                         module_files)

    # This is a similar approach to what OSTree does in the deploy command.
    # It searches for the directory under /usr/lib/modules/<kver> which
    # contains a vmlinuz file.
    for module_dir in module_dirs:
        directory_name = module_dir["name"]

        # Check if the directory contains a vmlinuz image if so it is our
        # kernel directory
        files = ls(repo, f"/usr/lib/modules/{directory_name}", commit)
        if any(file for file in files if file["name"] == "vmlinuz"):
            kernel_version = directory_name
            break

    return kernel_version

def copy_file(repo, commit, input_file, output_file):
    """ copy a file within a OSTree repo to somewhere else

        args:
            repo(OSTree.Repo) - repo object
            commit(str) - the ostree commit hash or name
            input_file - the input file path in the OSTree
            output_file - the output file paht where we want to copy to
        raises:
            TorizonCoreBuilderError - if commit does not exist
    """

    # Make sure we don't end the path with / because this confuses ostree
    ret, root, _commit = repo.read_commit(commit)
    if not ret:
        raise TorizonCoreBuilderError(f"Can not read commit: {commit}")

    input_stream = root.resolve_relative_path(input_file).read()

    output_stream = Gio.File.new_for_path(output_file).create(
        Gio.FileCreateFlags.NONE, None)
    if not output_stream:
        raise TorizonCoreBuilderError(f"Can not create file {output_file}")

    # Move input to output stream
    output_stream.splice(input_stream, Gio.OutputStreamSpliceFlags.CLOSE_SOURCE,
                      None)
