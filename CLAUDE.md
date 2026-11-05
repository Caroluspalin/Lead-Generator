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
- Skeemamuutokset Alembicilla: jokaisesta mallimuutoksesta uusi migraatio (`alembic revision --autogenerate -m "..."`), tarkista generoitu tiedosto käsin ennen committia. Tuotannossa (Postgres) skeema luodaan ja päivitetään vain `alembic upgrade head` -komennolla; `create_db_and_tables` toimii vain dev-SQLitessä.
- Dev-SQLite: aja `alembic upgrade head`. Jos kanta on luotu `create_all`:lla (ei `alembic_version`-taulua), joko poista `agency_hunter.db` ja aja `alembic upgrade head`, tai `alembic stamp head` jos skeema vastaa jo malleja.

## Komennot

```bash
# Frontend
npm run dev

# Backend (backend/-kansiosta, venv aktiivisena)
cd backend && source venv/bin/activate && uvicorn app.main:app --reload

# Tietokantamigraatiot (backend/-kansiosta, venv aktiivisena, DATABASE_URL .env:stä)
cd backend && alembic upgrade head                              # aja kaikki migraatiot
cd backend && alembic revision --autogenerate -m "kuvaus"       # uusi migraatio mallimuutoksesta
cd backend && alembic check                                     # mallit vs. kanta, ei saa löytää eroja
cd backend && alembic downgrade -1                              # peru viimeisin migraatio

# Backend-testit (backend/-kansiosta, venv aktiivisena)
cd backend && source venv/bin/activate && pip install -r requirements-dev.txt && pytest

# Frontend-tarkistukset (samat kuin CI:ssä)
npm run lint && npm run build
```
