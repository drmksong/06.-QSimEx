from setuptools import setup, find_packages

setup(
    name='q_rock_simulator',
    version='0.2.0',
    description='Tunnel Q-System Spatial Analysis Simulator',
    author='Q-Rock Team',
    packages=find_packages(),
    python_requires='>=3.8',
    install_requires=[
        'numpy>=1.21.0',
        'scipy>=1.7.0',
        'matplotlib>=3.5.0',
        'pandas>=1.3.0',
        'scikit-learn>=1.0.0',
        'pyvista>=0.44.0',
    ],
    extras_require={
        'gui': ['PyQt6>=6.4.0'],
        'cadquery': ['cadquery>=2.3.0'],
    },
    entry_points={
        'console_scripts': [
            'qrock-cli=cli.commands:main',
            'qrock-gui=gui.main_window:main',
        ],
    },
)