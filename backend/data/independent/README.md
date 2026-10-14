# Independent held-out set: brief for outside writers

We test a tool that finds and hides personal data in transcripts of phone calls between a
Singapore bank and its clients. We need calls we did not write, because we wrote the tool and
our own test calls share our habits.

**Please write 10–15 short calls (6–15 lines each).** Vary them: card problems, transfers,
loans, scams, complaints, account changes, calls for a relative. Write the way people actually
talk: Singlish, Mandarin or Malay phrases, interruptions, people reading numbers out, the agent
asking for things in their own words. Some calls can be lowercase with no punctuation, the way
speech recognition writes them. You may use an LLM to help.

**Do not write real personal data.** Wherever a call mentions something sensitive, write a typed
placeholder instead of a value. We fill it with a fake, checksum-valid value, so the labels stay exact.

    {{PERSON}} {{NRIC}} {{PASSPORT}} {{PHONE}} {{EMAIL}} {{ADDRESS}} {{DOB}}
    {{ACCOUNT_NO}} {{IBAN}} {{CARD_NO}} {{CARD_EXPIRY}} {{TXN_REF}} {{AMOUNT}}
    {{OTP}} {{PIN}} {{CVV}} {{SECURITY_ANSWER}}
    {{LOCATION}} {{BRANCH}} {{SWIFT}} {{EMPLOYER}} {{OCCUPATION}} {{NATIONALITY}} {{DATE}}
    {{HEALTH}} {{LEGAL}} {{RELIGION}} {{PEP}}

If the sensitive thing is phrased in a way a placeholder cannot fill ("my nephew's company in
Hong Kong", "the chicken rice"), write the words and mark them yourself: `{{EMPLOYER:Lim and Sons}}`.

Start each call with `### <your initials><number> <high|low>`: `high` if the bank should refer it
to compliance (a scam or fraud report, or an overseas transfer of S$5,000 or more), `low` otherwise.
Each line starts with `A:` (agent) or `C:` (client); use `a:`/`c:` for lowercase speech-style lines.

    ### JT01 high
    A: Fraud line, can I have your name?
    C: {{PERSON}}. Someone called saying they're from MAS and I gave them the code.
    A: Which code?
    C: The {{OTP}} one.

## For the team

1. Concatenate the writers' files into `calls.txt` here. Do not edit them after reading them.
2. `python -m data.heldout freeze data/independent/calls.txt`, then commit `calls.txt` and
   `calls.txt.sha256` **before** running anything on them.
3. `python -m experiments.run e1` scores the set once per detector version. It refuses a set
   whose hash does not match. Do not tune on what it reports; the next fix needs the next set.
