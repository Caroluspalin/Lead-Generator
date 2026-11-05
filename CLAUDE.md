# Agency Hunter — Claude Instructions

## Dokumentaatio

- Nykytila ja arkkitehtuuri: [docs/save_state.md](docs/save_state.md)
- Roadmap (tehty + tuleva): [docs/roadmap.md](docs/roadmap.md)

## Koodaussäännöt

- Anna vain pyydetyt tiedostot. Älä kirjoita koodia jota ei pyydetty.
- Älä riko olemassa olevaa toiminnallisuutta. Testaa muutosten vaikutus.
- TypeScript: tarkat tyypit, ei `any`:a, ei turhia type assertion -kikkailuja.
- Python: type hintit funktioiden parametreissa ja paluuarvoissa.
- Älä lisää kommentteja jotka toistavat koodin. Kommentoi vain miksi, ei mitä.
- Älä refaktoroi tai siivoa koodia jota ei pyydetty muuttamaan.
- Älä luo uusia tiedostoja ellei se ole välttämätöntä. Suosi olemassa olevien muokkausta.
- Säilytä nykyinen tyyli: Tailwind-luokat inline, framer-motion animaatiot, sonner-toastit.
- Backend: `asyncio.to_thread()` kaikille blokkaaville kutsuille. Älä blokkaa event loopia.
- UI-kieli: englanti. Koodikommentit: suomi tai englanti, ei väliä.
- Turvakytkimet (MAX_SEARCH_CALLS, MAX_DETAIL_CALLS) ovat ehdottomia rajoja. Älä nosta niitä ilman lupaa.
- Poista `agency_hunter.db` ennen uudelleenkäynnistystä jos malleja on muutettu (ei Alembicia).

## Komennot

```bash
# Frontend
npm run dev

# Backend (backend/-kansiosta, venv aktiivisena)
cd backend && source venv/bin/activate && uvicorn app.main:app --reload

# Backend-testit (backend/-kansiosta, venv aktiivisena)
cd backend && source venv/bin/activate && pip install -r requirements-dev.txt && pytest

# Frontend-tarkistukset (samat kuin CI:ssä)
npm run lint && npm run build
```
