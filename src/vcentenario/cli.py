from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .config import (
    DEFAULT_DB_PATH,
    DEFAULT_SNAPSHOTS_DIR,
    KEEP_BATCHES,
    KEEP_COLLECTION_RUNS,
    KEEP_SNAPSHOTS_PER_CAMERA,
    KEEP_STATES,
)
from .service import VCentenarioService
from .utils import configure_logging, dumps_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Monitor MVP del Puente del Centenario")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help="Ruta a la base SQLite")
    parser.add_argument(
        "--snapshots-dir",
        type=Path,
        default=DEFAULT_SNAPSHOTS_DIR,
        help="Directorio donde se guardan snapshots de camaras",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Nivel de log (DEBUG, INFO, WARNING, ERROR)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Inicializa la base SQLite")

    run_once = subparsers.add_parser("run-once", help="Recoge una tanda y calcula el estado")
    run_once.add_argument("--json", action="store_true", help="Imprime salida JSON")

    latest = subparsers.add_parser("latest-state", help="Muestra el ultimo estado persistido")
    latest.add_argument("--json", action="store_true", help="Imprime salida JSON")

    cleanup = subparsers.add_parser("cleanup", help="Limpia histórico antiguo y compacta la base")
    cleanup.add_argument("--keep-states", type=int, default=KEEP_STATES, help="Estados a conservar")
    cleanup.add_argument(
        "--keep-runs", type=int, default=KEEP_COLLECTION_RUNS, help="Ejecuciones a conservar"
    )
    cleanup.add_argument(
        "--keep-batches",
        type=int,
        default=KEEP_BATCHES,
        help="Tandas de paneles e incidencias a conservar",
    )
    cleanup.add_argument(
        "--keep-snapshots-per-camera",
        type=int,
        default=KEEP_SNAPSHOTS_PER_CAMERA,
        help="Snapshots a conservar por cámara",
    )
    cleanup.add_argument("--vacuum", action="store_true", help="Ejecuta VACUUM tras limpiar")

    serve = subparsers.add_parser("serve", help="Lanza una app web sencilla para visualizar el estado")
    serve.add_argument("--host", default="127.0.0.1", help="Host donde escuchar")
    serve.add_argument("--port", type=int, default=8080, help="Puerto HTTP")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)
    service = VCentenarioService(db_path=args.db, snapshots_dir=args.snapshots_dir)

    if args.command == "init-db":
        service.init_db()
        print(f"Base inicializada en {args.db}")
        return 0

    if args.command == "run-once":
        result = service.run_once()
        if args.json:
            print(dumps_json(result))
        else:
            state = result["state"]
            print(
                f"Estado {state['traffic_level']} | score={state['traffic_score']} | "
                f"reversible={state['reversible_probable']} | confidence={state['confidence']}"
            )
            if result["warnings"]:
                print(f"Avisos: {len(result['warnings'])} | {' ; '.join(result['warnings'])}", file=sys.stderr)
        return 0

    if args.command == "latest-state":
        result = service.latest_state()
        if result is None:
            print("No hay estado persistido todavía.", file=sys.stderr)
            return 1
        if args.json:
            print(dumps_json(result))
        else:
            print(
                f"{result['generated_at']} | {result['traffic_level']} | "
                f"score={result['traffic_score']} | reversible={result['reversible_probable']}"
            )
        return 0

    if args.command == "cleanup":
        service.init_db()
        result = service.storage.prune_history(
            keep_states=args.keep_states,
            keep_collection_runs=args.keep_runs,
            keep_batches=args.keep_batches,
            keep_snapshots_per_camera=args.keep_snapshots_per_camera,
        )
        if args.vacuum:
            service.storage.vacuum()
        print(dumps_json({"cleanup": result, "vacuum": args.vacuum}))
        return 0

    if args.command == "serve":
        from .webapp import DashboardServer

        DashboardServer(service=service, host=args.host, port=args.port).serve()
        return 0

    parser.error(f"Comando no soportado: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
