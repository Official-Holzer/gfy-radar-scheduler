"""Publish archive coverage and the twelve most recent completed collection batches."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def percent(part, total):
    return (f"{100 * part / total:.2f}".replace(".", ",") + " %") if total else "–"


def update(run_id, timestamp, checked, saved, reused, errors):
    root = Path(__file__).resolve().parents[1]
    seen = set()
    fresh = set()
    observations = 0
    catalog = {row["id"] for row in json.loads((root / "catalog.json").read_text("utf-8"))}
    cutoff = (timestamp - timedelta(days=7)).timestamp() * 1000
    for path in (root / "prices").glob("*.json"):
        if path.stem not in catalog:
            continue
        for point in json.loads(path.read_text("utf-8-sig")):
            if point["source"] == "amazon" and point["cents"] > 0:
                seen.add(path.stem)
                observations += 1
                if cutoff <= point["observed_at"] <= timestamp.timestamp() * 1000:
                    fresh.add(path.stem)

    history = root / "recent-runs.json"
    runs = json.loads(history.read_text()) if history.exists() else []
    runs = [r for r in runs if r["id"] != run_id]
    runs.append(dict(id=run_id, date=timestamp.isoformat(), checked=checked, saved=saved, reused=reused, errors=errors))
    runs = sorted(runs, key=lambda r: r["date"], reverse=True)[:12]
    history.write_text(json.dumps(runs, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# GFY Preisradar · Sammelstatistik", "",
        "Stand " + timestamp.strftime("%d.%m.%Y %H:%M UTC"), "",
        "| Katalogabdeckung im GitHub-Sammelarchiv | Produkte | Anteil |",
        "|---|---:|---:|",
        f"| Mindestens ein bestätigter Preis | {len(seen)} von {len(catalog)} | {percent(len(seen),len(catalog))} |",
        f"| Bestätigter Preis in den letzten 7 Tagen | {len(fresh)} von {len(catalog)} | {percent(len(fresh),len(catalog))} |", "",
        f"Insgesamt {observations} gespeicherte Amazon-Preisbeobachtungen für Katalogprodukte. "
        "Ein Produkt kann mehrere Beobachtungen haben. Importierte Archivpreise und reine Website-Abfragen sind ausgenommen.", "",
        "## Letzte Sammelläufe", "",
        "| Lauf (UTC) | Prüfungen | Mit Preis | Trefferquote | Neu gespeichert | Fehler |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for run in runs:
        hits = run["saved"] + run["reused"]
        stamp = datetime.fromisoformat(run["date"]).strftime("%d.%m. %H:%M")
        url = "https://github.com/Official-Holzer/gfy-radar-scheduler/actions/runs/" + run["id"]
        lines.append(f"| [{stamp}]({url}) | {run['checked']} | {hits} | {percent(hits,run['checked'])} | {run['saved']} | {run['errors']} |")
    lines.extend(["", "Eine Prüfung zählt als Treffer, wenn der Sammler einen aktuellen Preis bestätigt. "
                  "Bereits gespeicherte Treffer erhöhen die Trefferquote, erzeugen aber keinen doppelten Eintrag."])
    (root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    stamp = datetime.fromisoformat(sys.argv[6]) if len(sys.argv) > 6 else datetime.now(timezone.utc)
    update(sys.argv[1], stamp, *map(int, sys.argv[2:6]))
