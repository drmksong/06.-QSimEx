"""PyVista 기반 3D 가시화 도구."""

from __future__ import annotations

from pathlib import Path


class PyVistaViewer:
    def __init__(self, case_dir: str | Path):
        self.case_dir = Path(case_dir)

    def show(self,
             scalar_name: str = 'Qprime',
             show_domain_slice: bool = True,
             show_volume_outline: bool = True,
             show_face_traces: bool = True,
             opacity_joints: float = 0.22,
             opacity_tunnel: float = 0.12,
             screenshot_path: str | Path | None = None,
             off_screen: bool = False):
        try:
            import pyvista as pv
        except Exception as exc:  # pragma: no cover
            raise RuntimeError('PyVista is required for 3D viewing') from exc

        meshes = self._load_meshes(pv)
        plotter = pv.Plotter(off_screen=off_screen)
        plotter.set_background('white')

        if 'domain' in meshes:
            domain = meshes['domain']
            if show_volume_outline:
                plotter.add_mesh(domain.outline(), color='black', line_width=1)

            if show_domain_slice:
                scalar = scalar_name if scalar_name in domain.cell_data else None
                if scalar is None and 'Q' in domain.cell_data:
                    scalar = 'Q'
                if scalar is None and 'Qprime' in domain.cell_data:
                    scalar = 'Qprime'
                if scalar is not None:
                    slice_mesh = domain.slice(normal='x', origin=domain.center)
                    plotter.add_mesh(slice_mesh, scalars=scalar, cmap='RdYlGn', opacity=0.95)

        if 'joints' in meshes:
            plotter.add_mesh(
                meshes['joints'],
                color='#d4a017',
                opacity=opacity_joints,
                smooth_shading=True,
            )

        if 'tunnel' in meshes:
            plotter.add_mesh(
                meshes['tunnel'],
                color='#355c7d',
                opacity=opacity_tunnel,
                style='wireframe',
                line_width=2,
            )

        if 'boreholes' in meshes:
            plotter.add_mesh(meshes['boreholes'], color='#c2185b', line_width=4)

        if show_face_traces:
            for trace in meshes.get('face_traces', []):
                plotter.add_mesh(trace, color='#00acc1', line_width=2)

        plotter.show_axes()
        plotter.add_text(self.case_dir.name, font_size=12, color='black')
        plotter.view_isometric()

        if screenshot_path is not None:
            plotter.screenshot(str(screenshot_path), transparent_background=False)

        if not off_screen:
            plotter.show()

    def _load_meshes(self, pv):
        meshes = {}

        domain_path = self.case_dir / 'domain_fields.vti'
        if domain_path.exists():
            meshes['domain'] = pv.read(str(domain_path))

        joints_path = self.case_dir / 'joints_all.vtp'
        if joints_path.exists():
            meshes['joints'] = pv.read(str(joints_path))

        tunnel_path = self.case_dir / 'tunnel.vtp'
        if tunnel_path.exists():
            meshes['tunnel'] = pv.read(str(tunnel_path))

        boreholes_path = self.case_dir / 'boreholes.vtp'
        if boreholes_path.exists():
            meshes['boreholes'] = pv.read(str(boreholes_path))

        face_traces = []
        face_dir = self.case_dir / 'face_traces'
        if face_dir.exists():
            for path in sorted(face_dir.glob('*.vtp')):
                try:
                    face_traces.append(pv.read(str(path)))
                except Exception:
                    continue
        if face_traces:
            meshes['face_traces'] = face_traces

        return meshes