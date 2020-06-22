import os
import sys
import logging
import subprocess
import traceback
from tcbuilder.backend import isolate

def isolate_subcommand(args):
    log = logging.getLogger("torizon." + __name__)  # use name hierarchy for "main" to be the parent
    try:
        ret = isolate.isolate_user_changes(args)
        if ret == isolate.NO_CHANGES:
            print("no change is made in /etc by user")

        log.info("isolation command completed")
    except Exception as ex:
        if hasattr(ex, "msg"):
            log.error(ex.msg)  # msg from all kinds of Exceptions
            log.info(ex.det)  # more elaborative message

        log.debug(traceback.format_exc())  # full traceback to be shown for debugging only

def init_parser(subparsers):
    subparser = subparsers.add_parser("isolate", help="""\
    capture /etc changes.
    """)

    subparser.add_argument("--diff-directory", dest="diff_dir",
                           help="""Directory for changes to be stored on the host system.
                            Must be a file system capable of carrying Linux file system 
                            metadata (Unix file permissions and xattr).""")
    subparser.add_argument("--remote-ip", dest="remoteip",
                           help="""name/IP of remote machine""",
                           required=True)
    subparser.add_argument("--remote-username", dest="remote_username",
                           help="""user name of remote machine""",
                           required=True)
    subparser.add_argument("--remote-password", dest="remote_password",
                           help="""password of remote machine""",
                           required=True)

    subparser.set_defaults(func=isolate_subcommand)