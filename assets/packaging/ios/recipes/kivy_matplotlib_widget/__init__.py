"""Pure-Python recipe for kivy_matplotlib_widget.

The package registers NavigationIcons.ttf from its own fonts directory at
import time, so setup.py install must keep that file in site-packages.
"""

import os

import sh
from kivy_ios.toolchain import PythonRecipe, shprint


class KivyMatplotlibWidgetRecipe(PythonRecipe):
    version = "0.16.0"
    url = "https://github.com/mp-007/kivy_matplotlib_widget/archive/refs/tags/v{version}.tar.gz"
    depends = ["python3", "kivy", "matplotlib"]

    def install_python_package(self, name=None, env=None, is_dir=True):
        # setup.py lists kivy and matplotlib as install requirements. They are
        # already built for iOS; do not let the host interpreter download them.
        plat = list(self.platforms_to_build)[0]
        if env is None:
            env = self.get_recipe_env(plat)
        os.chdir(self.get_build_dir(plat))
        hostpython = sh.Command(self.ctx.hostpython)
        shprint(
            hostpython,
            "setup.py",
            "install",
            "-O2",
            "--single-version-externally-managed",
            "--record",
            "install-record.txt",
            "--root",
            self.ctx.python_prefix,
            "--prefix",
            "",
            _env=env,
        )


recipe = KivyMatplotlibWidgetRecipe()
