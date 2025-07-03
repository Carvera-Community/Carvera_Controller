from pythonforandroid.recipe import CythonRecipe
from pythonforandroid.toolchain import current_directory, shprint
import sh

class PyQuickLZRecipe(CythonRecipe):
    version = '1.4.1'
    url = 'https://files.pythonhosted.org/packages/6e/02/4ecd44e3cdf2ecd81d6040928b7aac894e241ae700e81a0aada50d0c36b0/pyquicklz-1.4.1.tar.gz'
    depends = ['python3', 'setuptools', 'cython']
    name = 'pyquicklz'
    call_hostpython_via_targetpython = False

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        
        # Set proper compilation flags for the target architecture
        if arch.arch == 'arm64-v8a':
            env['CFLAGS'] += ' -fPIC -march=armv8-a'
            env['LDFLAGS'] += ' -fPIC'
            print(f"[PyQuickLZ] Building for arm64-v8a with CFLAGS: {env['CFLAGS']}")
        elif arch.arch == 'armeabi-v7a':
            env['CFLAGS'] += ' -fPIC -march=armv7-a -mfpu=neon -mfloat-abi=softfp'
            env['LDFLAGS'] += ' -fPIC'
            print(f"[PyQuickLZ] Building for armeabi-v7a with CFLAGS: {env['CFLAGS']}")
        else:
            print(f"[PyQuickLZ] Unknown architecture: {arch.arch}")
        
        # Ensure we're using the correct compiler for the architecture
        env['CC'] = arch.get_env()['CC']
        env['CXX'] = arch.get_env()['CXX']
        
        return env

    def build_arch(self, arch):
        print(f"[PyQuickLZ] Building for architecture: {arch.arch}")
        
        # Use the parent class build_arch method
        super().build_arch(arch)

recipe = PyQuickLZRecipe() 