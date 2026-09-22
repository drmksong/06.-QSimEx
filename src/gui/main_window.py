"""
PyQt6 기반 메인 윈도우
"""

import sys
import numpy as np

try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGroupBox, QLabel, QComboBox, QPushButton, QSpinBox, QDoubleSpinBox,
        QTextEdit, QTabWidget, QProgressBar, QSplitter, QTableWidget,
        QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox, QCheckBox
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    from PyQt6.QtGui import QFont
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    GUI_AVAILABLE = True
except ImportError:
    GUI_AVAILABLE = False

from core.case_library import CaseLibrary
from core.domain import RockDomain
from core.tunnel_old import Tunnel
from core.comparison import ComparisonEngine


# ────────────────────────────────────────
# Worker Thread
# ────────────────────────────────────────
if GUI_AVAILABLE:

    class AnalysisWorker(QThread):
        """백그라운드 분석 스레드"""
        progress = pyqtSignal(str)          # ← 변경: Signal → pyqtSignal
        finished = pyqtSignal(dict)         # ← 변경
        error = pyqtSignal(str)             # ← 변경

        def __init__(self, case, face_positions=None, bh_window=3):
            super().__init__()
            self.case = case
            self.face_positions = face_positions
            self.bh_window = bh_window

        def run(self):
            try:
                self.progress.emit("3D 도메인 생성 중...")
                domain = RockDomain(self.case)
                domain.generate(verbose=False)

                self.progress.emit("터널 & 시추공 설정...")
                tunnel = Tunnel(domain)

                self.progress.emit("비교 분석 수행 중...")
                engine = ComparisonEngine(tunnel)
                comparisons = engine.progressive_comparison(
                    self.face_positions, self.bh_window)
                summary = engine.summary_statistics(comparisons)

                self.finished.emit({
                    'domain': domain,
                    'tunnel': tunnel,
                    'engine': engine,
                    'comparisons': comparisons,
                    'summary': summary,
                })
            except Exception as e:
                self.error.emit(str(e))


    # ────────────────────────────────────────
    # Matplotlib Canvas for Qt
    # ────────────────────────────────────────
    class MplCanvas(FigureCanvas):
        def __init__(self, parent=None, width=8, height=5):
            self.fig = Figure(figsize=(width, height), dpi=100)
            self.axes = self.fig.add_subplot(111)
            super().__init__(self.fig)


    # ────────────────────────────────────────
    # 메인 윈도우
    # ────────────────────────────────────────
    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Q-Rock Simulator v0.2 — 터널 Q값 공간분석")
            self.setMinimumSize(1400, 900)

            self.domain = None
            self.tunnel = None
            self.comparisons = None
            self.summary = None
            self.worker = None

            self._setup_ui()

        def _setup_ui(self):
            central = QWidget()
            self.setCentralWidget(central)
            main_layout = QHBoxLayout(central)

            # ── 좌측: 설정 패널 ──
            left_panel = QVBoxLayout()
            left_panel.setSpacing(10)

            # 케이스 선택
            case_group = QGroupBox("분석 케이스")
            case_layout = QVBoxLayout()
            self.case_combo = QComboBox()
            for name, case in CaseLibrary.get_all_cases().items():
                self.case_combo.addItem(f"{name} — {case.description}", name)
            case_layout.addWidget(self.case_combo)

            self.seed_spin = QSpinBox()
            self.seed_spin.setRange(1, 99999)
            self.seed_spin.setValue(42)
            self.seed_spin.setPrefix("Seed: ")
            case_layout.addWidget(self.seed_spin)

            self.bh_window_spin = QSpinBox()
            self.bh_window_spin.setRange(1, 20)
            self.bh_window_spin.setValue(3)
            self.bh_window_spin.setPrefix("BH Window: ")
            case_layout.addWidget(self.bh_window_spin)

            case_group.setLayout(case_layout)
            left_panel.addWidget(case_group)

            # 실행 버튼
            self.run_btn = QPushButton("▶ 분석 실행")
            self.run_btn.setMinimumHeight(50)
            self.run_btn.setFont(QFont("", 14, QFont.Weight.Bold))  # ← 변경: QFont.Bold → QFont.Weight.Bold
            self.run_btn.clicked.connect(self._on_run)
            left_panel.addWidget(self.run_btn)

            # 진행 상태
            self.progress_label = QLabel("대기 중...")
            left_panel.addWidget(self.progress_label)
            self.progress_bar = QProgressBar()
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setVisible(False)
            left_panel.addWidget(self.progress_bar)

            # 내보내기 버튼
            export_group = QGroupBox("내보내기")
            export_layout = QVBoxLayout()

            self.export_paraview_btn = QPushButton("📦 ParaView 내보내기")
            self.export_paraview_btn.clicked.connect(self._on_export_paraview)
            self.export_paraview_btn.setEnabled(False)
            export_layout.addWidget(self.export_paraview_btn)

            self.export_json_btn = QPushButton("💾 JSON 내보내기")
            self.export_json_btn.clicked.connect(self._on_export_json)
            self.export_json_btn.setEnabled(False)
            export_layout.addWidget(self.export_json_btn)

            export_group.setLayout(export_layout)
            left_panel.addWidget(export_group)

            left_panel.addStretch()

            # ── 우측: 결과 탭 ──
            self.tabs = QTabWidget()

            # 탭 1: 로그
            self.log_text = QTextEdit()
            self.log_text.setReadOnly(True)
            self.log_text.setFont(QFont("Courier", 10))
            self.tabs.addTab(self.log_text, "📋 로그")

            # 탭 2: 비교 테이블
            self.result_table = QTableWidget()
            self.tabs.addTab(self.result_table, "📊 비교 결과")

            # 탭 3: Q 비교 그래프
            self.canvas_comparison = MplCanvas(width=10, height=6)
            self.tabs.addTab(self.canvas_comparison, "📈 Q 비교")

            # 탭 4: 도메인 슬라이스
            self.canvas_slice = MplCanvas(width=12, height=5)
            self.tabs.addTab(self.canvas_slice, "🗺️ 도메인 단면")

            # 탭 5: 산포도
            self.canvas_scatter = MplCanvas(width=7, height=6)
            self.tabs.addTab(self.canvas_scatter, "⬡ 산포도")

            # 탭 6: 통계 요약
            self.summary_text = QTextEdit()
            self.summary_text.setReadOnly(True)
            self.summary_text.setFont(QFont("Courier", 11))
            self.tabs.addTab(self.summary_text, "📊 통계 요약")

            # 레이아웃 조합
            splitter = QSplitter(Qt.Orientation.Horizontal)  # ← 변경: Qt.Horizontal → Qt.Orientation.Horizontal
            left_widget = QWidget()
            left_widget.setLayout(left_panel)
            left_widget.setMaximumWidth(350)
            splitter.addWidget(left_widget)
            splitter.addWidget(self.tabs)
            splitter.setSizes([300, 1100])

            main_layout.addWidget(splitter)

        # ── 이벤트 핸들러 ──
        def _on_run(self):
            case_key = self.case_combo.currentData()
            case = CaseLibrary.get_all_cases()[case_key]
            case.seed = self.seed_spin.value()

            self.run_btn.setEnabled(False)
            self.progress_bar.setVisible(True)
            self.log_text.clear()
            self._log(f"🚀 분석 시작: {case.name}")
            self._log(f"   {case.description}")
            self._log(f"   Seed={case.seed}\n")

            self.worker = AnalysisWorker(
                case, bh_window=self.bh_window_spin.value()
            )
            self.worker.progress.connect(self._on_progress)
            self.worker.finished.connect(self._on_finished)
            self.worker.error.connect(self._on_error)
            self.worker.start()

        def _on_progress(self, msg: str):
            self.progress_label.setText(msg)
            self._log(f"  ⏳ {msg}")

        def _on_finished(self, result: dict):
            self.progress_bar.setVisible(False)
            self.run_btn.setEnabled(True)
            self.export_paraview_btn.setEnabled(True)
            self.export_json_btn.setEnabled(True)
            self.progress_label.setText("✅ 완료!")

            self.domain = result['domain']
            self.tunnel = result['tunnel']
            self.comparisons = result['comparisons']
            self.summary = result['summary']

            self._log("\n✅ 분석 완료!")
            self._log(f"   비교 단면: {self.summary['n_faces']}개")
            self._log(f"   Q 상관계수: {self.summary['Q_correlation']:.4f}")
            self._log(f"   Q 일치율: {self.summary['Q_match_rate']:.1f}%")

            self._update_table()
            self._update_comparison_plot()
            self._update_slice_plot()
            self._update_scatter_plot()
            self._update_summary()

        def _on_error(self, msg: str):
            self.progress_bar.setVisible(False)
            self.run_btn.setEnabled(True)
            self.progress_label.setText("❌ 오류 발생")
            self._log(f"\n❌ 오류: {msg}")
            QMessageBox.critical(self, "오류", msg)

        def _log(self, msg: str):
            self.log_text.append(msg)

        # ── 결과 테이블 ──
        def _update_table(self):
            cols = ['Chainage', 'Q_Face', 'Q_BH', 'Q_Ratio',
                    'Qp_Face', 'Qp_BH', 'Qp_Ratio', 'Match']
            self.result_table.setColumnCount(len(cols))
            self.result_table.setHorizontalHeaderLabels(cols)
            self.result_table.setRowCount(len(self.comparisons))

            for row, c in enumerate(self.comparisons):
                match = "✅" if 0.5 <= c['Q_ratio'] <= 2.0 else "❌"
                values = [
                    f"{c['face_x_coord']:.1f}",
                    f"{c['Q_face_mean']:.3f}",
                    f"{c['Q_borehole_mean']:.3f}",
                    f"{c['Q_ratio']:.3f}",
                    f"{c['Qp_face_mean']:.3f}",
                    f"{c['Qp_borehole_mean']:.3f}",
                    f"{c['Qp_ratio']:.3f}",
                    match,
                ]
                for col, val in enumerate(values):
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)  # ← 변경: Qt.AlignCenter
                    self.result_table.setItem(row, col, item)

            self.result_table.horizontalHeader().setSectionResizeMode(
                QHeaderView.ResizeMode.Stretch)  # ← 변경: QHeaderView.Stretch

        # ── 비교 그래프 ──
        def _update_comparison_plot(self):
            self.canvas_comparison.fig.clear()
            axes = self.canvas_comparison.fig.subplots(1, 2)

            x = [c['face_x_coord'] for c in self.comparisons]

            ax = axes[0]
            ax.plot(x, [c['Q_face_mean'] for c in self.comparisons],
                    'ro-', label='Face Q', lw=2, ms=4)
            ax.plot(x, [c['Q_borehole_mean'] for c in self.comparisons],
                    'b^--', label='Borehole Q', lw=2, ms=4)
            ax.set_xlabel('Chainage (m)')
            ax.set_ylabel('Q')
            ax.set_title('Q: Borehole vs Face')
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.set_yscale('log')

            ax = axes[1]
            ax.plot(x, [c['Qp_face_mean'] for c in self.comparisons],
                    'ro-', label="Face Q'", lw=2, ms=4)
            ax.plot(x, [c['Qp_borehole_mean'] for c in self.comparisons],
                    'b^--', label="Borehole Q'", lw=2, ms=4)
            ax.set_xlabel('Chainage (m)')
            ax.set_ylabel("Q'")
            ax.set_title("Q': Borehole vs Face")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.set_yscale('log')

            self.canvas_comparison.fig.tight_layout()
            self.canvas_comparison.draw()

        # ── 도메인 슬라이스 ──
        def _update_slice_plot(self):
            self.canvas_slice.fig.clear()
            ax = self.canvas_slice.fig.add_subplot(111)

            z_idx = self.domain.nz // 2
            data = self.domain.Q_field[:, :, z_idx]

            im = ax.imshow(data.T, origin='lower', aspect='auto',
                           extent=[0, self.domain.nx * self.domain.dx,
                                   0, self.domain.ny * self.domain.dy],
                           cmap='RdYlGn')
            self.canvas_slice.fig.colorbar(im, ax=ax, label='Q')
            ax.set_xlabel('X - Tunnel Axis (m)')
            ax.set_ylabel('Y - Transverse (m)')
            ax.set_title(f'Q Distribution @ Z={z_idx * self.domain.dz:.0f}m')

            self.canvas_slice.fig.tight_layout()
            self.canvas_slice.draw()

        # ── 산포도 ──
        def _update_scatter_plot(self):
            self.canvas_scatter.fig.clear()
            ax = self.canvas_scatter.fig.add_subplot(111)

            fQ = [c['Q_face_mean'] for c in self.comparisons]
            bQ = [c['Q_borehole_mean'] for c in self.comparisons]
            ax.scatter(fQ, bQ, c='steelblue', s=50, alpha=0.7, edgecolors='white')

            lims = [max(min(fQ + bQ) * 0.5, 0.01), max(fQ + bQ) * 2]
            ax.plot(lims, lims, 'k--', lw=2, label='1:1')
            ax.set_xscale('log')
            ax.set_yscale('log')
            ax.set_xlabel('Face Q (mean)')
            ax.set_ylabel('Borehole Q (mean)')
            ax.set_title(f'r = {self.summary["Q_correlation"]:.3f}')
            ax.legend()
            ax.grid(True, alpha=0.3)

            self.canvas_scatter.fig.tight_layout()
            self.canvas_scatter.draw()

        # ── 통계 요약 ──
        def _update_summary(self):
            s = self.summary
            text = f"""
{'='*50}
  Q-Rock Simulator — 종합 통계 요약
{'='*50}

  비교 단면 수:        {s['n_faces']}

  ── Q (전체) ──
  비율 평균:           {s['Q_ratio_mean']:.3f} ± {s['Q_ratio_std']:.3f}
  비율 중앙값:         {s['Q_ratio_median']:.3f}
  상관계수 (r):        {s['Q_correlation']:.4f}
  Log-RMSE:            {s['Q_log_RMSE']:.4f}
  일치율 (0.5~2×):     {s['Q_match_rate']:.1f}%

  ── Q' (Jw=1, SRF=1) ──
  비율 평균:           {s['Qp_ratio_mean']:.3f} ± {s['Qp_ratio_std']:.3f}
  비율 중앙값:         {s['Qp_ratio_median']:.3f}
  상관계수 (r):        {s['Qp_correlation']:.4f}
  일치율 (0.5~2×):     {s['Qp_match_rate']:.1f}%

  ── 도메인 정보 ──
  절리군:              {self.domain.case.joint_config.n_sets}개
  Jn:                  {self.domain.case.joint_config.Jn}
  총 절리:             {len(self.domain.dfn.joints)}개
  RQD mean:            {self.domain.fields['RQD'].mean():.1f}
  Q  mean:             {self.domain.Q_field.mean():.3f}
  Q' mean:             {self.domain.Qprime_field.mean():.3f}

{'='*50}
"""
            self.summary_text.setPlainText(text)

        # ── 내보내기 ──
        def _on_export_paraview(self):
            if self.domain is None:
                return
            dir_path = QFileDialog.getExistingDirectory(self, "출력 디렉토리 선택")
            if dir_path:
                from export.export_manager import ExportManager
                exporter = ExportManager(self.domain, self.tunnel, output_dir=dir_path)
                exporter.export_all()
                QMessageBox.information(self, "완료", f"ParaView 파일 저장: {dir_path}")

        def _on_export_json(self):
            if self.comparisons is None:
                return
            path, _ = QFileDialog.getSaveFileName(self, "JSON 저장", "", "JSON (*.json)")
            if path:
                import json
                data = {
                    'case': self.domain.case.name,
                    'summary': self.summary,
                    'comparisons': [
                        {k: v for k, v in c.items()
                         if k not in ['face_stats', 'boreholes']}
                        for c in self.comparisons
                    ],
                }
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False,
                              default=lambda o: float(o) if isinstance(o, np.floating) else
                              int(o) if isinstance(o, np.integer) else
                              o.tolist() if isinstance(o, np.ndarray) else str(o))
                QMessageBox.information(self, "완료", f"JSON 저장: {path}")


def main():
    """GUI 진입점"""
    if not GUI_AVAILABLE:
        print("❌ PyQt6가 설치되지 않았습니다.")
        print("   pip install PyQt6")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()