from kivy_ios.toolchain import PythonRecipe, CythonRecipe, Recipe, shprint
import os


class PySerialRecipe(PythonRecipe):
    version = "3.4"
    url = "https://github.com/pyserial/pyserial/archive/refs/tags/v{version}.tar.gz"

    depends = ['python3']

recipe = PySerialRecipe()
