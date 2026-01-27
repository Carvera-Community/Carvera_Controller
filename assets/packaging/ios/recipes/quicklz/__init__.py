from kivy_ios.toolchain import PythonRecipe, CythonRecipe, Recipe, shprint
import os


class QuicklzRecipe(CythonRecipe):
    version = "1.4.1"
    url = "https://github.com/douban/pyquicklz/archive/refs/tags/{version}.tar.gz"

    depends = ['python3']
    library = "libquicklz.a"

    python_depends = ['setuptools']
    call_hostpython_via_targetpython = False

    def get_recipe_env(self, arch=None):
        env = super().get_recipe_env(arch)
        env['OTHER_LDFLAGS'] += "-static"
        return env

recipe = QuicklzRecipe()
