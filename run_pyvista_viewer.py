"""Open an exported case directory in a PyVista 3D viewer."""

import argparse
from pathlib import Path

from src.visualization.pyvista_viewer import PyVistaViewer


def main():
    parser = argparse.ArgumentParser(description='Open PyVista 3D viewer for a case export')
    parser.add_argument('--case-dir', required=True, help='Export directory, e.g. output/<case_name>')
    parser.add_argument('--scalar', default='Qprime', help='Scalar field for the domain slice')
    parser.add_argument('--screenshot', default=None, help='Optional screenshot output path (default: output/figures/<case>_pyvista.png)')
    parser.add_argument('--off-screen', action='store_true', help='Render off screen (useful for screenshot capture)')
    parser.add_argument('--no-save', action='store_true', help='Disable automatic screenshot save')
    args = parser.parse_args()

    case_dir = Path(args.case_dir)
    default_shot = Path('output/figures') / f'{case_dir.name}_pyvista.png'
    screenshot_path = None if args.no_save else (Path(args.screenshot) if args.screenshot else default_shot)

    if screenshot_path is not None:
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)

    viewer = PyVistaViewer(args.case_dir)
    viewer.show(
        scalar_name=args.scalar,
        screenshot_path=screenshot_path,
        off_screen=args.off_screen or screenshot_path is not None,
    )

    if screenshot_path is not None:
        print(f'Saved screenshot: {screenshot_path}')


if __name__ == '__main__':
    main()