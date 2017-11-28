# -*- python -*-
VERSION = '2.3.0'
APPNAME = 'hamster-time-tracker'
top = '.'
out = 'build'

import intltool, gnome
import os

def configure(conf):
    conf.check_tool('python')
    conf.check_tool('misc')
    conf.check_python_version((2,4,2))

    conf.check_tool('gnome intltool dbus')
    # conf.check_tool('gconf requests beaker wnck pytz jira dateutil')

    conf.define('ENABLE_NLS', 1)
    conf.define('HAVE_BIND_TEXTDOMAIN_CODESET', 1)

    conf.define('VERSION', VERSION)
    conf.define('GETTEXT_PACKAGE', "hamster-time-tracker")
    conf.define('PACKAGE', "hamster-time-tracker")
    conf.define('PYEXECDIR', conf.env["PYTHONDIR"]) # i don't know the difference

    # avoid case when we want to install globally (prefix=/usr) but sysconfdir
    # was not specified
    if conf.env['SYSCONFDIR'] == '/usr/etc':
        conf.define('SYSCONFDIR', '/etc')
    else:
        conf.define('SYSCONFDIR', conf.env['SYSCONFDIR'])

    conf.define('prefix', conf.env["PREFIX"]) # to keep compatibility for now

    conf.sub_config("help")


def set_options(opt):
    # options for disabling pyc or pyo compilation
    opt.tool_options("python")
    opt.tool_options("misc")
    opt.tool_options("gnu_dirs")


def build(bld):
    bld.install_files('${LIBDIR}/hamster-time-tracker',
                      """src/hamster-service
                         src/hamster-windows-service
                      """,
                      chmod = 0755)

    bld.install_as('${BINDIR}/hamster', "src/hamster-cli", chmod = 0755)


    bld.install_files('${SYSCONFDIR}/bash_completion.d','src/hamster.bash')


    # set correct flags in defs.py
    bld.new_task_gen("subst",
                     source= "src/hamster/defs.py.in",
                     target= "src/hamster/defs.py",
                     install_path="${PYTHONDIR}/hamster",
                     dict = bld.env
                    )

    bld.install_files('${PYTHONDIR}/hamster', 'src/hamster/*.py')
    bld.install_files('${PYTHONDIR}/hamster/widgets', 'src/hamster/widgets/*.py')
    bld.install_files('${PYTHONDIR}/hamster/lib', 'src/hamster/lib/*.py')

    bld.new_task_gen("subst",
                     source= "org.gnome.hamster.service.in",
                     target= "org.gnome.hamster.service",
                     install_path="${DATADIR}/dbus-1/services",
                     dict = bld.env
                    )
    bld.new_task_gen("subst",
                     source= "org.gnome.hamster.Windows.service.in",
                     target= "org.gnome.hamster.Windows.service",
                     install_path="${DATADIR}/dbus-1/services",
                     dict = bld.env
                    )

    bld.add_subdirs("po help data")


    def post(ctx):
        # Postinstall tasks:
        # gnome.postinstall_scrollkeeper('hamster-time-tracker') # Installing the user docs
        gnome.postinstall_schemas('hamster-time-tracker') # Installing GConf schemas
        gnome.postinstall_icons() # Updating the icon cache


    bld.add_post_fun(post)


def copy_help(ctx):
    os.system('cp -R build/default/help/ .')


def push_release(ctx):
    """copies generated page files to sources so that they are packaged on dist
       then creates the tarball and pushes to git master
       TODO - this should depend and fail if distcheck fails. also it looks
              suspiciously non-native
    """
    tarball = dist(APPNAME, VERSION)

    import os
    os.system('git tag %s-%s' % (APPNAME, VERSION)) 
    #os.system('cp %s /tmp/' %tarball)
    #os.system('scp %s tbaugis@master.gnome.org:/home/users/tbaugis' % tarball)
    #os.system("ssh tbaugis@master.gnome.org 'install-module %s'" % tarball)


def release(ctx):
    """packaging a version"""
    import Scripting
    Scripting.commands += ['build', 'copy_help', 'push_release']
