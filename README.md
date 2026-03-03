# Concurrent Image Processing System

A command-line tool for applying image filters concurrently, built with Python using multithreading and multiprocessing. Developed as a university project for the Parallel Algorithms course.

---

## Tech Stack

- **Python 3** — core language
- **Pillow** — image loading and saving
- **NumPy** — pixel-level array manipulation
- **SciPy** — Gaussian filter implementation
- **threading** — concurrent command handling, locks, condition variables
- **multiprocessing** — process pool for parallel filter execution

---

## Architecture

Each CLI command runs in its own **thread**. Filter processing is offloaded to a `multiprocessing.Pool` (CPU count − 2 workers) for true parallelism. A dedicated background thread monitors a task queue and updates task statuses upon completion.

Thread safety is enforced via:
- `threading.Lock` on shared image and task registries
- `threading.Condition` for task synchronization (e.g. blocking deletion until pending tasks finish)

---

## Filters

| Filter | Description |
|--------|-------------|
| `Grayscale` | Converts to grayscale using weighted RGB (0.299R + 0.587G + 0.114B) |
| `Gaussian Blur` | Per-channel Gaussian blur (σ=3) |
| `Brightness Adjustment` | Adjusts brightness relative to mean pixel intensity |

Each processed image tracks its full **filter history** and **ancestor lineage**.

---

## Commands
```
dodaj <path>        Add an image to the registry
obradi <file.json>  Apply a filter (configured via JSON)
izlistaj            List all registered images
opisi <id>          Show image transformation history and ancestors
obrisi <id>         Safely delete an image (waits for pending tasks)
izadji              Shut down the application
```

---

## JSON Task Format
```json
{
  "slika_id": 1,
  "tip_filtera": "Gaussian Blur",
  "putanja": "slike\\output.png"
}
```

Supported values for `tip_filtera`: `Grayscale`, `Gaussian Blur`, `Brightness Adjustment`

---

## Getting Started
```bash
pip install pillow numpy scipy
python Main.py
```

> Make sure a `slike/` directory exists in the project root before adding images.

---
