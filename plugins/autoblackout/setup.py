from setuptools import setup, find_packages

version = '1.0.0'

setup(
    name="alerta-autoblackout",
    version=version,
    description='Alerta plugin for automatic blackouts based on events',
    url='https://github.com/michael-chambers/alerta-contrib',
    license='MIT',
    author='Michael Chambers',
    author_email='mchambers@mirantis.com',
    packages=find_packages(),
    py_modules=['alerta_autoblackout'],
    include_package_data=True,
    zip_safe=True,
    entry_points={
        'alerta.plugins': [
            'autoblackout = alerta_autoblackout:AutoBlackout'
        ]
    }
)
