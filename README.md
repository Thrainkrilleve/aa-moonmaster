# aa-moonmaster

**Moon Master** is an [Alliance Auth](https://allianceauth.readthedocs.io/) plugin that unifies moon mining and Metenox passive-harvest tracking into a single app with real-time profitability calculations.

## Features

- **Unified moon database** — track ore composition, rarity, and location for every moon your corp controls, with no inter-app dependencies.
- **Athanor drill extractions** — import ESI extraction events, monitor status, and view estimated value.
- **Metenox passive harvest** — track fuel expiry, goo-bay fill percentage, and receive Discord alerts before you run out.
- **Real-time pricing** — pull ESI average prices *or* Fuzzwork Jita buy prices (user-selectable).
- **Profitability calculator** — compare Athanor drill mining vs. Metenox passive harvest side-by-side:
  - Drill mode: full ore volume × price with configurable fleet-share percentage
  - Metenox mode: 30,000 m³/hr at 40% reprocess yield, minus fuel block + magmatic gas costs
  - Tax engine: alliance tax, corp tax, structure reprocessing tax, and fixed sov/upkeep costs
- **Reports view** — rank all tracked moons by net ISK/month, with the best-option recommendation highlighted.
- **Discord webhook alerts** — low fuel, goo bay ≥ 80%, and extraction chunk arriving within 1 hour.

## Requirements

- Alliance Auth ≥ 4.0.0
- Python ≥ 3.10
- `django-eveuniverse` ≥ 1.0.0
- `requests` ≥ 2.28.0

## Installation

1. Install the package:
   ```bash
   pip install aa-moonmaster
   ```

2. Add `"moonmaster"` to `INSTALLED_APPS` in your Auth `local.py`:
   ```python
   INSTALLED_APPS += ["moonmaster"]
   ```

3. Run migrations:
   ```bash
   python manage.py migrate moonmaster
   ```

4. Add the URL hook in your `urls.py` (Auth handles this automatically via the `url_hook`).

5. (Optional) Configure the Discord webhook URL in `local.py`:
   ```python
   MOONMASTER_DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
   ```

6. Add periodic tasks to your task scheduler (Django-Q / Celery Beat):

   | Task | Interval |
   |---|---|
   | `moonmaster.tasks.update_prices` | every 12 h |
   | `moonmaster.tasks.update_all_structures` | every 1 h |
   | `moonmaster.tasks.update_extractions` | every 10 min |
   | `moonmaster.tasks.send_alerts` | every 10 min |

## Permissions

| Permission | Who needs it |
|---|---|
| `moonmaster.basic_access` | All members who should see the app |
| `moonmaster.manage_moons` | Directors / FC who add/edit moons & structures |
| `moonmaster.view_reports` | FC / leadership who can view profit reports |

## Configuration

| Setting | Default | Description |
|---|---|---|
| `MOONMASTER_DISCORD_WEBHOOK_URL` | `None` | Discord webhook for alerts |

## Development

```bash
git clone https://github.com/yourorg/aa-moonmaster
cd aa-moonmaster
pip install -e ".[dev]"
python manage.py test moonmaster
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT
