# Demand test — complete playbook

**Goal:** find out in one week whether German dental depots will pay for
competitor price monitoring. Cost: your time. No code written.

**Decision rule, set BEFORE you start:** 15 companies contacted.
- 2+ ask what it costs → build it
- 0–1 ask → stop, the niche is not there

Write that number down now. Deciding the threshold after seeing the results is
how you talk yourself into a business that does not exist.

---

## The legal constraint (read once, then follow it)

§7 UWG requires **prior express consent for advertising email in Germany —
including B2B.** No exception. A competitor or Wettbewerbsverband can send an
Abmahnung: lawyer costs plus a penalty-bearing cease-and-desist.

**Telephone is lawful** for B2B under *mutmaßliche Einwilligung* (presumed
consent) when the offer objectively relates to that company's business. Price
monitoring offered to a price-competing dental depot clears that comfortably.

So the order is:
1. **Phone** — primary channel, lawful, fastest signal
2. **Contact form on their own website** — they published it to receive
   enquiries; much safer than cold email to a harvested address
3. **LinkedIn** — acceptable, slower
4. **Cold email — only AFTER they have said yes on the phone or in the form**

Never send an unsolicited email to an address you scraped from an Impressum.
That is exactly the case §7 covers.

---

## Target list (contact data from public Impressum, verify before dialling)

Phone numbers were auto-extracted and a couple are certainly wrong — always
confirm on the site before calling.

| # | Company | Contact person | Phone | Notes |
|---|---|---|---|---|
| 1 | kaniedenta.de | Stephan Holtkamp (GF) | 05221-34550 | Shopware, mid-size, competes with dentalbauer |
| 2 | trade4dent.com | Michael Herdt (GF) | 069-50608880 | Shopware, price-positioned by name |
| 3 | klapperzaehnchen.de | — | 0741-17400-450 | small; their sitemap is broken = thin tech resource |
| 4 | direct-onlinehandel.de | — | see site | platform unknown, likely small |
| 5 | b2b-hygiene.com | — | see site | adjacent vertical, same problem |
| 6 | geizdental.de | — | see site | price-positioned; may want to watch others |
| 7 | dentalbauer.de | Marcus Dahlinger (GF) | 00800 77655440 | large — likely already has a tool. Ask anyway, the "no" is informative |

### Finding the other 8

Search these terms and take depots that are NOT the market leader:

- `Dentaldepot` / `Dentalhandel` / `Dentalversand`
- `Praxisbedarf Zahnarzt online kaufen`
- `Zahnärztlicher Fachhandel B2B`
- On any depot site: their "Marken" page tells you which brands to compare

**Qualify before calling.** A target is worth a call only if:
- they sell online with **visible prices** (otherwise there is nothing to watch)
- they have **at least 2 named competitors** you could actually monitor
- they are not the biggest player in their segment

Disqualify: pure manufacturers, pharmacy wholesalers, anyone with no webshop.

---

## Step by step

### Day 1 — build the list (2h)
Fill the tracking sheet (`demand_test_tracker.csv`) to 15 rows. For each:
company, URL, contact person, phone, and **the two competitors you would
monitor for them**. That last column matters — it makes the call concrete.

### Day 2–4 — call (2h/day, 5 calls a day)
Best window: **Tue–Thu, 09:00–11:30 or 14:00–16:00.** Avoid Monday morning and
Friday afternoon.

Ask for the Geschäftsführer at a small depot; Leiter E-Commerce or
Vertriebsleitung at a larger one. Not marketing.

### Day 5 — contact forms
Everyone you could not reach by phone gets the form message below.

### Day 6–7 — count and decide
Apply the rule you wrote down on Day 1.

---

## Phone script

The first sentence establishes the business connection, which is what makes
the call lawful. Do not open with small talk.

> „Guten Tag, mein Name ist Taras. Ich rufe an, weil ich ein Werkzeug
> entwickelt habe, das Preise von Dentaldepots automatisch vergleicht — also
> zum Beispiel Ihre Preise gegen **[Wettbewerber A]** und **[Wettbewerber B]**,
> umgerechnet auf Preis pro Stück, weil die Packungsgrößen ja unterschiedlich
> sind.
>
> Ich möchte Ihnen nichts verkaufen, ich habe eine konkrete Frage:
> **Beobachten Sie die Preise Ihrer Mitbewerber im Moment manuell — und wenn
> ja, wie viel Zeit kostet Sie das?**"

**Then stop talking.** That question is the entire experiment. Their answer is
the data point. Resist filling the silence.

### If the answer is "ja, manuell"
> „Wie oft machen Sie das — wöchentlich, monatlich? Und wer macht das bei
> Ihnen?"

Then:
> „Ich könnte Ihnen einmal kostenlos eine Beispielauswertung für zwei, drei
> Ihrer Wettbewerber schicken. Wenn ich Ihnen das per E-Mail zusende — wäre das
> in Ordnung?"

**That last question is the consent.** Once they say yes on the phone, email is
lawful. Note the date and time in the tracker.

### If the answer is "wir nutzen schon ein Tool"
> „Welches denn, wenn ich fragen darf? Und funktioniert das auch bei Shops, wo
> die Preise erst nach dem Login sichtbar sind?"

This is the **most valuable answer in the whole test.** If everyone already has
a tool and it covers login-gated shops, the niche does not exist and you have
saved yourself three months.

### If the answer is "kein Interesse"
> „Verstehe. Darf ich ganz kurz fragen — weil die Preise für Sie nicht
> relevant sind, oder weil Sie es anders lösen?"

Then thank them and hang up. One follow-up question, no persuasion.

---

## Contact form message

> **Betreff:** Frage zu Wettbewerbspreisen
>
> Guten Tag,
>
> ich entwickle ein Werkzeug, das Preise von Dentaldepots automatisch
> vergleicht — normalisiert auf Preis pro Stück, da die Packungsgrößen
> zwischen Anbietern abweichen.
>
> Bevor ich das weiterentwickle, möchte ich eine Frage klären:
> **Verfolgen Sie die Preise Ihrer Mitbewerber aktuell manuell?**
>
> Über eine kurze Rückmeldung würde ich mich sehr freuen.
>
> Viele Grüße
> Taras [Nachname]
> [Telefon]

Short on purpose. One question, no attachment, no pitch, no calendar link.

---

## Follow-up email — ONLY after they said yes

> **Betreff:** Beispielauswertung Wettbewerbspreise — wie besprochen
>
> Guten Tag Herr/Frau [Name],
>
> vielen Dank für das Gespräch vorhin. Wie besprochen sende ich Ihnen eine
> Beispielauswertung.
>
> Verglichen habe ich [X] Artikel aus dem Bereich [Kategorie] zwischen
> [Wettbewerber A] und [Wettbewerber B]. Die Preise sind auf Preis pro Stück
> bzw. pro Gramm umgerechnet, weil die Packungsgrößen abweichen — sonst
> vergleicht man Packungsgrößen statt Preise.
>
> Zwei Hinweise zur Einordnung:
> - Artikel mit mehreren Varianten habe ich ausgeschlossen, dort ist die
>   Zuordnung noch nicht eindeutig.
> - Die Zuordnung der Artikel erfolgt über Produktnamen, da die Shops keine
>   EAN veröffentlichen. Bei Unsicherheit ist der Übereinstimmungswert
>   angegeben.
>
> Falls das für Sie nützlich ist: ich könnte das wöchentlich automatisiert
> laufen lassen, mit Ihrem eigenen Sortiment als Grundlage.
>
> Viele Grüße
> Taras [Nachname]

The two "Hinweise" are deliberate. Stating the limitations is what separates
you from a vendor sending an inflated number — and you already know from
testing that variants and name-matching are the weak points.

---

## Pricing, if they ask

Do not quote a number on the first call. Say:

> „Das hängt davon ab, wie viele Wettbewerber und wie viele Artikel. Größenordnung
> 250 bis 400 Euro im Monat. Ich schicke Ihnen die Beispielauswertung, und wenn
> das für Sie passt, rechnen wir es konkret."

Anchor first, exact number later, after they have seen output.

---

## What to record for every contact

Use `demand_test_tracker.csv`. The columns that matter:

- **reached** — did you speak to a decision maker at all
- **monitors_competitors** — yes/no/unknown
- **how** — manual / tool / not at all
- **tool_name** — if they named one, WRITE IT DOWN
- **asked_price** — yes/no ← **this is the metric**
- **consent_email** — did they agree to receive the example
- **quote** — their exact words, one line

The `quote` column is worth more than the counts. Three people saying "das
macht bei uns eine Mitarbeiterin jeden Montag" tells you the product; a tally
of yes/no does not.

---

## Honest expectations

- Reaching a decision maker: roughly **1 in 3 calls**
- So 15 companies ≈ **5 real conversations**
- Of those, 2 asking about price is a strong signal at this sample size

If you get 5 conversations and nobody has the problem, that is a real answer,
not bad luck. Stop and keep the week.
