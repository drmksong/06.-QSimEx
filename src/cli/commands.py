"""
CLI 커맨드 인터페이스
"""

import argparse
import sys
import json
import os
import numpy as np

from src.core.case_library import CaseLibrary, CaseLoader, CaseScanner
from src.core.domain import RockDomain
from src.core.tunnel import Tunnel
from src.core.comparison import ComparisonEngine
from src.visualization.plots import Visualizer


def main():
    parser = argparse.ArgumentParser(
        description="Q-Rock Simulator: 터널 시추공 vs 막장면 Q값 비교",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 케이스 목록 (cases/ 디렉토리 스캔)
  python run_cli.py --list-cases

  # 이름으로 실행 (cases/granite_2sets.yaml 자동 탐색)
  python run_cli.py --case granite_2sets --visualize

  # YAML 파일 직접 지정
  python run_cli.py --case-file cases/my_custom.yaml --visualize

  # 기본 YAML 파일 생성 (처음 한 번)
  python run_cli.py --init-cases

  # 전체 옵션
  python run_cli.py --case granite_2sets --paraview --visualize --export result.json
  python run_cli.py --case-file cases/fault_zone_4sets.yaml --face-positions 20 40 60 80

  # 배치 실행 (cases/ 디렉토리 내 모든 케이스)
  python run_cli.py --batch --visualize
        """,
    )

    # ── 입력 옵션 ──
    input_group = parser.add_argument_group("입력")
    input_group.add_argument(
        "--case",
        type=str,
        default=None,
        help="케이스 이름 (cases/ 디렉토리에서 자동 탐색)",
    )
    input_group.add_argument(
        "--case-file", type=str, default=None, help="YAML 케이스 파일 직접 지정"
    )
    input_group.add_argument(
        "--case-dir", type=str, default="cases", help="케이스 디렉토리 (기본: cases/)"
    )

    # ── 관리 옵션 ──
    manage_group = parser.add_argument_group("관리")
    manage_group.add_argument(
        "--list-cases", action="store_true", help="사용 가능한 케이스 목록"
    )
    manage_group.add_argument(
        "--init-cases", action="store_true", help="기본 케이스 YAML 파일 생성"
    )

    # ── 분석 옵션 ──
    analysis_group = parser.add_argument_group("분석")
    analysis_group.add_argument(
        "--face-positions",
        nargs="+",
        type=int,
        default=None,
        help="굴진면 위치 (x 격자 인덱스)",
    )
    analysis_group.add_argument(
        "--bh-window", type=int, default=3, help="시추공 평균 윈도우 (기본: 3)"
    )
    analysis_group.add_argument(
        "--seed", type=int, default=None, help="랜덤 시드 오버라이드"
    )
    analysis_group.add_argument(
        "--backend",
        type=str,
        default="auto",
        choices=["auto", "cuda", "mps", "mlx", "cpu"],
        help="가속 백엔드 (기본: auto)",
    )
    analysis_group.add_argument(
        "--batch-size", type=int, default=500, help="GPU 배치 크기 (기본: 500)"
    )

    # ── 출력 옵션 ──
    output_group = parser.add_argument_group("출력")
    output_group.add_argument(
        "--visualize", "-v", action="store_true", help="Matplotlib 시각화"
    )
    output_group.add_argument(
        "--verify-dfn", action="store_true", help="DFN 분포 검증 그래프"
    )
    output_group.add_argument(
        "--paraview", action="store_true", help="ParaView 파일 내보내기"
    )
    output_group.add_argument(
        "--pyvista", action="store_true", help="PyVista 3D 시각화 (내보내기 후 즉시 열기)"
    )
    output_group.add_argument("--export", type=str, default=None, help="결과 JSON 경로")
    output_group.add_argument(
        "--output-dir", type=str, default="output", help="출력 디렉토리 (기본: output)"
    )

    # ── 배치 옵션 ──
    batch_group = parser.add_argument_group("배치")
    batch_group.add_argument(
        "--batch", action="store_true", help="cases/ 내 모든 케이스 일괄 실행"
    )

    args = parser.parse_args()

    # ── 기본 YAML 생성 ──
    if args.init_cases:
        CaseLibrary.generate_default_yamls(args.case_dir)
        return

    # ── 케이스 목록 ──
    if args.list_cases:
        _list_cases(args.case_dir)
        return

    # ── 배치 실행 ──
    if args.batch:
        _run_batch(args)
        return

    # ── 단일 실행 ──
    case = _load_case(args)
    if case is None:
        parser.print_help()
        return

    if args.seed is not None:
        case.seed = args.seed

    _run_single(case, args)


def _list_cases(case_dir: str):
    """케이스 목록 출력"""
    print(f"\n📋 케이스 목록 (디렉토리: {case_dir}/)")
    print("─" * 70)

    # YAML 파일 스캔
    yaml_files = CaseScanner.scan_cases(case_dir)

    if yaml_files:
        for name, path in yaml_files.items():
            try:
                case = CaseLoader.load_yaml(path)
                jc = case.joint_config
                print(f"\n  📄 {name}")
                print(f"     파일: {path}")
                print(f"     설명: {case.description}")
                print(f"     도메인: {case.domain_size}, seed={case.seed}")
                print(f"     절리군: {jc.n_sets}개, Jn={jc.Jn}")
                for js in jc.joint_sets:
                    print(f"       - {js.summary()}")
            except Exception as e:
                print(f"\n  ⚠️ {name}: 로드 실패 ({e})")
    else:
        print(f"\n  ℹ️ {case_dir}/ 에 YAML 파일이 없습니다.")
        print(f"     기본 파일 생성: python run_cli.py --init-cases")
        print(f"\n  📦 내장 프리셋:")
        for name, case in CaseLibrary._builtin_cases().items():
            print(f"    • {name}: {case.description}")

    print()


def _load_case(args) -> "AnalysisCase":
    """인자에서 케이스 로드"""
    # 파일 직접 지정
    if args.case_file:
        try:
            case = CaseLoader.load_yaml(args.case_file)
            print(f"  📄 YAML 로드: {args.case_file}")
            return case
        except Exception as e:
            print(f"❌ YAML 로드 실패: {e}")
            sys.exit(1)

    # 이름으로 검색
    if args.case:
        try:
            case = CaseLibrary.load_case(args.case, args.case_dir)
            return case
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(1)

    # 기본값
    print("ℹ️ --case 또는 --case-file을 지정하세요.")
    print("   목록 보기: python run_cli.py --list-cases")
    return None


def _run_single(case, args):
    """단일 케이스 실행"""
    # 배너
    print(f"\n{'='*60}")
    print(f"  🏔️  Q-Rock Simulator v0.2")
    print(f"{'='*60}")
    print(f"  케이스:   {case.name}")
    print(f"  설명:     {case.description}")
    print(f"  도메인:   {case.domain_size}")
    print(f"  시드:     {case.seed}")
    case.joint_config.summary()
    print(f"{'='*60}\n")

    # [1] 도메인 생성
    print("[1/4] 3D 암반 도메인 생성...")
    domain = RockDomain(case)
    # domain.generate(verbose=True, backend='auto', batch_size=500)
    domain.generate(verbose=True, backend=args.backend, batch_size=args.batch_size)

    # DFN 검증
    if args.verify_dfn:
        print("\n📊 DFN 분포 검증...")
        Visualizer.plot_dfn_verification(domain.dfn, case.joint_config)

    # [2] 터널
    print("\n[2/4] 터널 & 시추공 설정...")
    tunnel = Tunnel(domain)
    for i, (y, z) in enumerate(tunnel.borehole_positions):
        names = ["Center", "Top", "Bottom"]
        bh_name = names[i] if i < 3 else f"BH-{i}"
        print(f"  시추공 {bh_name}: y_idx={y}, z_idx={z}")

    # [3] 비교 분석
    print("\n[3/4] 비교 분석 수행...")
    engine = ComparisonEngine(tunnel)
    comparisons = engine.progressive_comparison(
        face_positions=args.face_positions, borehole_window=args.bh_window
    )
    summary = engine.summary_statistics(comparisons)

    # [4] 결과
    print("\n[4/4] 결과 출력")
    engine.print_report(comparisons, summary)

    # 시각화
    if args.visualize:
        print("\n📈 시각화 생성...")
        Visualizer.plot_comparison(comparisons)
        Visualizer.plot_domain_slice(domain, param="Q")
        Visualizer.plot_domain_slice(domain, param="RQD")
        if comparisons:
            mid = len(comparisons) // 2
            face = tunnel.sample_face(comparisons[mid]["face_x"])
            Visualizer.plot_face_detail(face, domain)

    # ParaView
    if args.paraview:
        print("\n📦 ParaView 내보내기...")
        from src.export.export_manager import ExportManager

        exporter = ExportManager(domain, tunnel, output_dir=args.output_dir)
        face_m = None
        if args.face_positions:
            face_m = [p * case.grid_spacing[0] for p in args.face_positions]
        exporter.export_all(face_positions_m=face_m)

    if args.pyvista:
        print("\n🧭 PyVista 3D 시각화...")
        from src.export.export_manager import ExportManager
        from src.visualization.pyvista_viewer import PyVistaViewer

        exporter = ExportManager(domain, tunnel, output_dir=args.output_dir)
        face_m = None
        if args.face_positions:
            face_m = [p * case.grid_spacing[0] for p in args.face_positions]
        exporter.export_all(face_positions_m=face_m)
        viewer = PyVistaViewer(exporter.base_dir)
        viewer.show()

    # JSON
    if args.export:
        _export_json(args.export, case, comparisons, summary)

    print(f"\n🏁 완료!")


def _run_batch(args):
    """cases/ 내 모든 케이스 일괄 실행"""
    cases = CaseLibrary.get_all_cases(args.case_dir)

    if not cases:
        print("❌ 실행할 케이스가 없습니다.")
        return

    print(f"\n🔄 배치 실행: {len(cases)}개 케이스")
    all_summaries = {}

    for i, (name, case) in enumerate(cases.items()):
        print(f"\n{'━'*60}")
        print(f"  [{i+1}/{len(cases)}] {name}: {case.description}")
        print(f"{'━'*60}")

        if args.seed is not None:
            case.seed = args.seed

        try:
            domain = RockDomain(case)
            # domain.generate(verbose=False)
            domain.generate(
                verbose=True, backend=args.backend, batch_size=args.batch_size
            )
            tunnel = Tunnel(domain)
            engine = ComparisonEngine(tunnel)
            comparisons = engine.progressive_comparison(borehole_window=args.bh_window)
            summary = engine.summary_statistics(comparisons)

            all_summaries[name] = summary

            q_corr = summary.get('Q_correlation', summary.get('Q_corr', 0.0))
            qp_corr = summary.get('Qp_correlation', summary.get('Qp_corr', 0.0))
            q_match = summary.get('Q_match_rate', summary.get('Q_match_normal', 0.0))
            qp_match = summary.get('Qp_match_rate', summary.get('Qp_match_normal', 0.0))
            print(
                f"  Q  상관계수: {q_corr:.4f}, 일치율: {q_match:.1f}%"
            )
            print(
                f"  Q' 상관계수: {qp_corr:.4f}, 일치율: {qp_match:.1f}%"
            )

            if args.paraview:
                from src.export.export_manager import ExportManager

                exporter = ExportManager(domain, tunnel, output_dir=args.output_dir)
                exporter.export_all()

        except Exception as e:
            print(f"  ❌ 실패: {e}")
            all_summaries[name] = {"error": str(e)}

    # 배치 요약
    print(f"\n{'='*70}")
    print(f"  📊 배치 실행 요약")
    print(f"{'='*70}")
    print(
        f"  {'케이스':<25} │ {'Q_r':>6} │ {'Q_match':>8} │ {'Qp_r':>6} │ {'Qp_match':>8}"
    )
    print(f"  {'─'*25} │ {'─'*6} │ {'─'*8} │ {'─'*6} │ {'─'*8}")

    for name, s in all_summaries.items():
        if "error" in s:
            print(f"  {name:<25} │ {'ERROR':>6} │ {'':>8} │ {'':>6} │ {'':>8}")
        else:
            q_corr = s.get('Q_correlation', s.get('Q_corr', 0.0))
            qp_corr = s.get('Qp_correlation', s.get('Qp_corr', 0.0))
            q_match = s.get('Q_match_rate', s.get('Q_match_normal', s.get('Q_match', 0.0)))
            qp_match = s.get('Qp_match_rate', s.get('Qp_match_normal', s.get('Qp_match', 0.0)))
            print(
                f"  {name:<25} │ {q_corr:>6.3f} │ "
                f"{q_match:>7.1f}% │ "
                f"{qp_corr:>6.3f} │ "
                f"{qp_match:>7.1f}%"
            )

    # 배치 JSON 내보내기
    if args.export:
        _export_json(args.export, None, None, all_summaries)

    print(f"\n🏁 배치 완료!")


def _export_json(filepath, case, comparisons, summary):
    """JSON 내보내기"""
    data = {"summary": summary}
    if case:
        data["case"] = case.name
    if comparisons:
        data["comparisons"] = [
            {k: v for k, v in c.items() if k not in ["face_stats", "boreholes"]}
            for c in comparisons
        ]

    def convert(obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return str(obj)

    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=convert)
    print(f"  💾 JSON 저장: {filepath}")


if __name__ == "__main__":
    main()
