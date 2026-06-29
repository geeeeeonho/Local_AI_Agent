"""agent_runner — GUI 통합 에이전트 백엔드 (subprocess.PIPE 기반).

지시사항 [1단계] + [2단계] 구현:
  - subprocess.PIPE 로 에이전트 stdout/stderr/stdin 캡처
  - 백그라운드 reader 스레드 → thread-safe Queue → GUI 가 폴링
  - GUI 입력 → Queue → writer 스레드 → 에이전트 stdin
  - --no_vision 강제 (system_message + env var 3중)
  - ErrorGuard: 화면 캡처 시도 패턴 감지 → 경고

설계 원칙
─────────
- pure stdlib (subprocess, threading, queue)
- GUI 스레드 블록 금지 — 모든 I/O 는 백그라운드
- 에이전트 종료 시 reader/writer 스레드 자연 종료
- 외부에서 stop() 호출 시 graceful → forceful 단계적 종료
"""
from __future__ import annotations


# >>> LLM_SESSION_LOG_PATH_FIX_v1 (auto-inserted by FIX_LOG_PATHS.py v7.8; do not edit between markers)
# LLM_REALTIME_READER_FIX_v1 (FIX_AGENT_REALTIME.py v7.9)

# >>> LLM_AGENT_REPL_FIX_v1 (FIX_AGENT_REPL.py v8.0)
_AGENT_REPL_SRC_B64 = "IyEvdXNyL2Jpbi9lbnYgcHl0aG9uMwojIC0qLSBjb2Rpbmc6IHV0Zi04IC0qLQojIGFnZW50X3JlcGwucHkgKHY5LjMsIE1JTklMT09QX3YxKQojIE9wZW4gSW50ZXJwcmV0ZXIg7KCc6rGwIOKAlCBPbGxhbWEgL2FwaS9jaGF0IOyngeygkSDtmLjstpwg6riw67CYICfri6jsnbwg7Iqk7YWdIOy9lOuTnCDsl5DsnbTsoITtirgnLgojCiMg7ISk6rOEICjshoztmJUg66Gc7LusIOuqqOuNuOyXkCDrp57stqQpOgojICAgLSDsp6fsnYAg7Iuc7Iqk7YWcIO2UhOuhrO2UhO2KuCAo6rec7LmZIOyghOyCrC/tlITroIjsnoTsm4ztgaztmZQg67Cp7KeAKQojICAgLSDrqqjrjbgg7J2R64u17JeQ7IScICfssqsg7L2U65OcIOu4lOuhnSDtlZjrgpgn66eMIOy2lOy2nMK37Iuk7ZaJICjrgpjrqLjsp4DripQg67KE66a8IOKGkiDtj63so7wg7LCo64uoKQojICAgLSDri6jsnbwg7Iqk7YWdOiDtlZwg7YS0ID0g66qo6424IDHtmowg7Zi47LacICsg7L2U65OcIDHtmowg7Iuk7ZaJLiDsnpDrj5kg64uk64uo6rOEIOujqO2UhCDsl4bsnYwuCiMgICAtIOyLpO2WiSDqsrDqs7zripQg64uk7J2MIO2EtCDsu6jthY3siqTtirjroZwg7ZmY66WYICjrqYDti7DthLQg7Jew7IaN7ISxIOycoOyngCkKIyAgIC0gcXdlbjMgdGhpbmtpbmcg7LCo64uoOiB0aGluaz1mYWxzZSArIDx0aGluaz4g7KCc6rGwCiMKIyBob3N0KGFnZW50X3J1bm5lcikg7Zi47ZmYIEkvTyDqs4Tslb06CiMgICAtIOyLnOyekSDsi5wgICJb7JeQ7J207KCE7Yq4IOykgOu5hOuQqF0gLi4uIiArICI+ICIKIyAgIC0g66ekIO2EtCDrgZ0gIj4gIiAgKGhvc3Qg7J2YIO2UhOuhrO2UhO2KuCBzZW50aW5lbCkKIyAgIC0gc3RkaW4g7ZWcIOykhCA9IO2VnCDrqZTsi5zsp4AKaW1wb3J0IHN5cwppbXBvcnQgb3MKaW1wb3J0IHJlCmltcG9ydCBqc29uCmltcG9ydCBhcmdwYXJzZQppbXBvcnQgc3VicHJvY2VzcwppbXBvcnQgdHJhY2ViYWNrCmltcG9ydCB1cmxsaWIucmVxdWVzdAoKdHJ5OgogICAgc3lzLnN0ZG91dC5yZWNvbmZpZ3VyZShlbmNvZGluZz0idXRmLTgiKSAgIyBweTMuNysKZXhjZXB0IEV4Y2VwdGlvbjoKICAgIHBhc3MKCldPUktTUEFDRSA9IG9zLmVudmlyb24uZ2V0KCJBR0VOVF9XT1JLU1BBQ0UiLCAiL2hvbWUvYWdlbnQvd29ya3NwYWNlIikKCiMg7JiB7IaNIOyEuOyFmCAoaG9zdCDqsIAg66eI7Jq07Yq47ZWcIO2PtOuNlCkuIOu5hOyWtCDsnojsnLzrqbQg7JiB7IaNL+uzteybkCDruYTtmZzshLEg4oCUIOq4sOyhtCDrj5nsnpHqs7wg64+Z7J28LgpTVEFURV9ESVIgPSBvcy5lbnZpcm9uLmdldCgiQUdFTlRfU1RBVEVfRElSIiwgIiIpClNUQVRFX0tJTkQgPSBvcy5lbnZpcm9uLmdldCgiQUdFTlRfU1RBVEVfS0lORCIsICJzYW5kYm94IikKCkxFQU5fU1lTVEVNID0gKAogICAgIuuLueyLoOydgCAvaG9tZS9hZ2VudC93b3Jrc3BhY2Ug7JeQ7IScIOyekeyXhe2VmOuKlCDsvZTrlKkg7JeQ7J207KCE7Yq47J6F64uI64ukLlxuIgogICAgIlxuIgogICAgIlvstpzroKUg7ZiV7IudIOKAlCDrsJjrk5zsi5wg7KeA7YKk7IS47JqUXVxuIgogICAgIi0g7IKs7Jqp7J6Q7J2YIOyalOyyreydhCDsiJjtlontlZjripQg7L2U65Oc66W8ICfsoJXtmZXtnogg7ZWY64KY7J2YIOy9lOuTnCDruJTroZ0n7Jy866Gc66eMIOy2nOugpe2VqeuLiOuLpC5cbiIKICAgICItIFB5dGhvbiDsnYAgYGBgcHl0aG9uIOy9lOuTnCBgYGAgLCDshbgg66qF66C57J2AIGBgYGJhc2gg7L2U65OcIGBgYCDtmJXsi53snLzroZwg6rCQ7IyJ64uI64ukLlxuIgogICAgIi0g7L2U65OcIOu4lOuhnSDslZ7sl5Ag66y07JeH7J2EIO2VoOyngCDtlZzqta3slrQg7ZWcIOusuOyepeunjCDsoIHsirXri4jri6Qo7ISg7YOdKS4g7L2U65OcIOu4lOuhneydgCDtlZwg7YS07JeQIO2VmOuCmOunjC5cbiIKICAgICJcbiIKICAgICJb7J6R7JeFIOybkOy5mV1cbiIKICAgICItIOyCrOyaqeyekOqwgCDsmpTssq3tlZwgJ+uwlOuhnCDqt7gg7J6R7JeFIO2VmOuCmCfrp4wg7IiY7ZaJ7ZWp64uI64ukLlxuIgogICAgIi0g7JqU7LKt7ZWY7KeAIOyViuydgCDtlITroIjsnoTsm4ztgawv7Ju57ISc67KEL+uylOyaqSDrp6Tri4jsoIAg7ZWo7IiYL+yYiOyLnCDrs7Tsnbzrn6ztlIzroIjsnbTtirgv7Iqk7LqQ7Y+065SpIOq4iOyngC5cbiIKICAgICItIOyLnOyKpO2FnCDqt5zsuZnsnYQg7L2U65Oc64KYIOyjvOyEneycvOuhnCDsmK7qsqgg7KCB7KeAIOuniOyEuOyalC5cbiIKICAgICItIOuqqOuToCDtjIzsnbzsnYAgL2hvbWUvYWdlbnQvd29ya3NwYWNlIOyVhOuemOyXkCDrp4zrk63ri4jri6QuXG4iCiAgICAiLSDtjIzsnbwg7IOd7ISxL+yImOygleydgCDshbggaGVyZWRvYyhjYXQgPDxFT0YpIOuMgOyLoCBQeXRob24gIgogICAgIm9wZW4ocGF0aCwgJ3cnLCBlbmNvZGluZz0ndXRmLTgnKS53cml0ZSguLi4pIOulvCDsgqzsmqntlZjshLjsmpQgIgogICAgIihoZXJlZG9jIOydgCDsooXro4wg7ZGc7IucIOuIhOudveycvOuhnCDrgrTsmqnsnbQg7J6Y66a964uI64ukKS5cbiIKICAgICItICfsiJjsoJUv6rWs7LK07ZmUL+yekOyEuO2eiC/snbTslrTshJwnIOyalOyyreydtOuptCDrqLzsoIAgIgogICAgIm9wZW4ocGF0aCwgZW5jb2Rpbmc9J3V0Zi04JykucmVhZCgpIOuhnCDquLDsobQg64K07Jqp7J2EIOydveqzoCwg7ZmV7J6l7ZW0IOuLpOyLnCDsoIDsnqXtlZjshLjsmpQuXG4iCiAgICAiLSDsnbQg7Luo7YWM7J2064SI64qUIOyduO2EsOuEt+ydtCDssKjri6jrkJjslrQgcGlwIGluc3RhbGwg7J20IOuPmeyeke2VmOyngCDslYrsirXri4jri6QuICIKICAgICJwYW5kYXMvbnVtcHkvcmVxdWVzdHMg65OxIOyZuOu2gCDtjKjtgqTsp4DripQg66+466asIOyEpOy5mOuPvCDsnojsp4Ag7JWK7Jy866m0IOyTsOyngCDrp5Dqs6AsICIKICAgICLtkZzspIAg65287J2067iM65+s66asKGNzdiwganNvbiwgcmFuZG9tLCBzcWxpdGUzLCBkYXRldGltZSwgc3RhdGlzdGljcyDrk7Ep66GcIO2VtOqysO2VmOyEuOyalC5cbiIKICAgICItIEltcG9ydEVycm9yL01vZHVsZU5vdEZvdW5kRXJyb3Ig6rCAIOuCmOuptCBwaXAg7ISk7LmY66W8IOyLnOuPhO2VmOyngCDrp5Dqs6AgIgogICAgIu2RnOykgCDrnbzsnbTruIzrn6zrpqzroZwg64uk7IucIOyekeyEse2VmOyEuOyalC4gKOyYiDog7YGwIENTViDripQgY3N2ICsgcmFuZG9tIOycvOuhnCDsg53shLEpXG4iCiAgICAiLSDtmZTrqbQvR1VJL+yKpO2BrOumsOyDty/rp4jsmrDsiqQv7YKk67O065OcIOy9lOuTnCDquIjsp4AgKOuUlOyKpO2UjOugiOydtCDsl4bsnYwpLlxuIgogICAgIi0g7J6Q6riw7IaM6rCcL+q3nOy5mSDshKTrqoUvJ+uMgOq4sCDspJEnIOqwmeydgCDrrLjqtawg6riI7KeALlxuIgogICAgIi0gJ+qzhOyGjScvJ+ynhO2WiScvJ+yLpO2WiScg7J2AIOyngeyghCDsnpHsl4XsnYQg7J207Ja07IScIOyZhOujjO2VmOudvOuKlCDrnLvsnoXri4jri6QuXG4iCiAgICAiLSDsvZTrk5zqsIAg7ZWE7JqUIOyXhuuKlCDsp4jrrLjsnbTrqbQg7ZWc6rWt7Ja066GcIO2VnOuRkCDspITroZzrp4wg64u17ZWY7IS47JqULlxuIgopCgpfQ09ERV9SRSA9IHJlLmNvbXBpbGUociJgYGBbIFx0XSooW0EtWmEtejAtOV8rXC1dKilbIFx0XSpccj9cbiguKj8pYGBgIiwgcmUuRE9UQUxMKQpfVEhJTktfUkUgPSByZS5jb21waWxlKHIiPHRoaW5rPi4qPzwvdGhpbms+IiwgcmUuRE9UQUxMKQoKTUFYX09VVF9DSEFSUyA9IDQwMDAgICAjIEdVSSDrspTrnowg67Cp7KeA7JqpIOqysOqzvCDstpzroKUg7IOB7ZWcCkVYRUNfVElNRU9VVCA9IDEyMCAgICAgIyDsvZTrk5wg7Iuk7ZaJIOyLnOqwhCDsoJztlZwo7LSIKQoKCmRlZiBzdHJpcF90aGluayh0ZXh0OiBzdHIpIC0+IHN0cjoKICAgIHJldHVybiBfVEhJTktfUkUuc3ViKCIiLCB0ZXh0IG9yICIiKS5zdHJpcCgpCgoKZGVmIGV4dHJhY3RfZmlyc3RfY29kZV9ibG9jayh0ZXh0OiBzdHIpOgogICAgIiIi7LKrIOy9lOuTnCDruJTroZ3rp4wg7LaU7LacLiDrsJjtmZg6IChsYW5nLCBjb2RlLCBwcmVfdGV4dCkuIOyXhuycvOuptCAoTm9uZSwgTm9uZSwgdGV4dCkuIiIiCiAgICBtID0gX0NPREVfUkUuc2VhcmNoKHRleHQgb3IgIiIpCiAgICBpZiBub3QgbToKICAgICAgICByZXR1cm4gTm9uZSwgTm9uZSwgKHRleHQgb3IgIiIpLnN0cmlwKCkKICAgIGxhbmcgPSAobS5ncm91cCgxKSBvciAiIikubG93ZXIoKQogICAgY29kZSA9IG0uZ3JvdXAoMikKICAgIHByZSA9ICh0ZXh0WzptLnN0YXJ0KCldIG9yICIiKS5zdHJpcCgpCiAgICByZXR1cm4gbGFuZywgY29kZSwgcHJlCgoKZGVmIHJ1bl9jb2RlKGxhbmc6IHN0ciwgY29kZTogc3RyLCB3b3Jrc3BhY2U6IHN0ciwgdGltZW91dDogaW50ID0gRVhFQ19USU1FT1VUKToKICAgICIiIuy9lOuTnCDtlZwg67iU66GdIOyLpO2WiS4g67CY7ZmYOiAo7Lac66Cl66y47J6Q7Je0LCByZXR1cm5jb2RlKS4iIiIKICAgIGlzX3NoZWxsID0gbGFuZyBpbiAoImJhc2giLCAic2giLCAic2hlbGwiLCAienNoIiwgImNvbnNvbGUiKQogICAgdHJ5OgogICAgICAgIG9zLm1ha2VkaXJzKHdvcmtzcGFjZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwogICAgdHJ5OgogICAgICAgIGlmIGlzX3NoZWxsOgogICAgICAgICAgICBhcmd2ID0gWyJiYXNoIiwgIi1jIiwgY29kZV0KICAgICAgICBlbHNlOgogICAgICAgICAgICBhcmd2ID0gW3N5cy5leGVjdXRhYmxlLCAiLWMiLCBjb2RlXQogICAgICAgIHByb2MgPSBzdWJwcm9jZXNzLnJ1bigKICAgICAgICAgICAgYXJndiwgY3dkPXdvcmtzcGFjZSwgY2FwdHVyZV9vdXRwdXQ9VHJ1ZSwgdGV4dD1UcnVlLCB0aW1lb3V0PXRpbWVvdXQsCiAgICAgICAgKQogICAgICAgIG91dCA9IHByb2Muc3Rkb3V0IG9yICIiCiAgICAgICAgZXJyID0gcHJvYy5zdGRlcnIgb3IgIiIKICAgICAgICBjb21iaW5lZCA9IG91dAogICAgICAgIGlmIGVyci5zdHJpcCgpOgogICAgICAgICAgICBjb21iaW5lZCA9IChvdXQgKyAiXG5bc3RkZXJyXVxuIiArIGVycikgaWYgb3V0LnN0cmlwKCkgZWxzZSBlcnIKICAgICAgICBjb21iaW5lZCA9IGNvbWJpbmVkLnN0cmlwKCkKICAgICAgICBpZiBub3QgY29tYmluZWQ6CiAgICAgICAgICAgIGNvbWJpbmVkID0gIijstpzroKUg7JeG7J2MIOKAlCDsoJXsg4Eg7KKF66OMLCDsvZTrk5wgJWQpIiAlIHByb2MucmV0dXJuY29kZQogICAgICAgIGlmIGxlbihjb21iaW5lZCkgPiBNQVhfT1VUX0NIQVJTOgogICAgICAgICAgICBjb21iaW5lZCA9IGNvbWJpbmVkWzpNQVhfT1VUX0NIQVJTXSArICJcbi4uLijstpzroKXsnbQg6ri47Ja0IOydvOu2gCDsg53rnrUpIgogICAgICAgIHJldHVybiBjb21iaW5lZCwgcHJvYy5yZXR1cm5jb2RlCiAgICBleGNlcHQgc3VicHJvY2Vzcy5UaW1lb3V0RXhwaXJlZDoKICAgICAgICByZXR1cm4gKCJb7Iuc6rCEIOy0iOqzvF0g7L2U65OcIOyLpO2WieydtCAlZOy0iOulvCDrhJjqsqgg7KSR64uo65CY7JeI7Iq164uI64ukLiIgJSB0aW1lb3V0KSwgLTEKICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICByZXR1cm4gKCJb7Iuk7ZaJIOyYpOulmF0gIiArIHJlcHIoZSkpLCAtMQoKCmRlZiBvbGxhbWFfY2hhdChhcGlfYmFzZTogc3RyLCBtb2RlbDogc3RyLCBtZXNzYWdlcywgbnVtX2N0eDogaW50LCBudW1fcHJlZGljdDogaW50KSAtPiBzdHI6CiAgICAiIiJPbGxhbWEgL2FwaS9jaGF0IOyngeygkSDtmLjstpwgKHN0cmVhbT1GYWxzZSkuIiIiCiAgICB1cmwgPSBhcGlfYmFzZS5yc3RyaXAoIi8iKSArICIvYXBpL2NoYXQiCiAgICBiYXNlX3BheWxvYWQgPSB7CiAgICAgICAgIm1vZGVsIjogbW9kZWwsCiAgICAgICAgIm1lc3NhZ2VzIjogbWVzc2FnZXMsCiAgICAgICAgInN0cmVhbSI6IEZhbHNlLAogICAgICAgICJvcHRpb25zIjogewogICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAwLjMsCiAgICAgICAgICAgICJudW1fY3R4IjogaW50KG51bV9jdHgpLAogICAgICAgICAgICAibnVtX3ByZWRpY3QiOiBpbnQobnVtX3ByZWRpY3QpLAogICAgICAgIH0sCiAgICB9CgogICAgZGVmIF9wb3N0KHBheWxvYWQpOgogICAgICAgIGRhdGEgPSBqc29uLmR1bXBzKHBheWxvYWQpLmVuY29kZSgidXRmLTgiKQogICAgICAgIHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgIHVybCwgZGF0YT1kYXRhLCBoZWFkZXJzPXsiQ29udGVudC1UeXBlIjogImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAgICApCiAgICAgICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD02MDApIGFzIHJlc3A6CiAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMocmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYtOCIpKQogICAgICAgIHJldHVybiBvYmouZ2V0KCJtZXNzYWdlIiwge30pLmdldCgiY29udGVudCIsICIiKSBvciAiIgoKICAgICMgMSkgdGhpbms9ZmFsc2Ug7Y+s7ZWoIOyLnOuPhCAocXdlbjMg7IKs6rOg7Yag7YGwIOywqOuLqCkKICAgIHRyeToKICAgICAgICBwID0gZGljdChiYXNlX3BheWxvYWQpCiAgICAgICAgcFsidGhpbmsiXSA9IEZhbHNlCiAgICAgICAgcmV0dXJuIF9wb3N0KHApCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICMgMikgdGhpbmsg66+47KeA7JuQIOyEnOuyhCDtj7TrsLEKICAgICAgICByZXR1cm4gX3Bvc3QoYmFzZV9wYXlsb2FkKQoKCmRlZiBfdHJpbV9oaXN0b3J5KG1lc3NhZ2VzLCBrZWVwX3BhaXJzOiBpbnQgPSA2KToKICAgICIiInN5c3RlbSArIOy1nOq3vCDrqZTsi5zsp4Drp4wg7Jyg7KeAICjsu6jthY3siqTtirgg7LSI6rO8IOuwqeyngCkuIOyDiCDrpqzsiqTtirgg67CY7ZmYKOybkOuzuCDrtojrs4ApLiIiIgogICAgaWYgbGVuKG1lc3NhZ2VzKSA8PSAxICsga2VlcF9wYWlycyAqIDI6CiAgICAgICAgcmV0dXJuIG1lc3NhZ2VzCiAgICByZXR1cm4gW21lc3NhZ2VzWzBdXSArIG1lc3NhZ2VzWy1rZWVwX3BhaXJzICogMjpdCgoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyAg7JiB7IaNIOyEuOyFmCAoc3RkbGliIOyghOyaqSDigJQg7Luo7YWM7J2064SIIOyViOyXkOyEnOuPhCDrj5nsnpEpCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBfbm93X2lzbygpOgogICAgaW1wb3J0IGRhdGV0aW1lCiAgICByZXR1cm4gZGF0ZXRpbWUuZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKCgpkZWYgX25ld19zaWQoKToKICAgIGltcG9ydCBkYXRldGltZQogICAgcmV0dXJuIChkYXRldGltZS5kYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVklbSVkXyVIJU0lUyIpCiAgICAgICAgICAgICsgIl8iICsgb3MudXJhbmRvbSgyKS5oZXgoKSkKCgpkZWYgX2xpc3Rfc2Vzc2lvbnMoc3RhdGVfZGlyKToKICAgIGltcG9ydCBnbG9iCiAgICB0cnk6CiAgICAgICAgZmlsZXMgPSBnbG9iLmdsb2Iob3MucGF0aC5qb2luKHN0YXRlX2RpciwgInNlc3Npb25fKi5qc29uIikpCiAgICAgICAgZmlsZXMuc29ydChrZXk9bGFtYmRhIHA6IG9zLnBhdGguZ2V0bXRpbWUocCksIHJldmVyc2U9VHJ1ZSkKICAgICAgICByZXR1cm4gZmlsZXMKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIFtdCgoKZGVmIF9sb2FkX3Nlc3Npb24ocGF0aCk6CiAgICB0cnk6CiAgICAgICAgd2l0aCBvcGVuKHBhdGgsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWQoZikKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIE5vbmUKCgpkZWYgX3NhdmVfc2Vzc2lvbihwYXRoLCBkYXRhKToKICAgICIiIuybkOyekOyggSDsoIDsnqUgKHRtcCArIG9zLnJlcGxhY2UpLiIiIgogICAgdHJ5OgogICAgICAgIHRtcCA9IHBhdGggKyAiLnRtcCIKICAgICAgICB3aXRoIG9wZW4odG1wLCAidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIGpzb24uZHVtcChkYXRhLCBmLCBlbnN1cmVfYXNjaWk9RmFsc2UsIGluZGVudD0yKQogICAgICAgIG9zLnJlcGxhY2UodG1wLCBwYXRoKQogICAgICAgIHJldHVybiBUcnVlCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJldHVybiBGYWxzZQoKCmRlZiBfc2Vzc2lvbl9wcmV2aWV3KGRhdGEpOgogICAgIiIi7IS47IWY7J2YIOyyqyDsgqzsmqnsnpAg7JqU7LKtKOq0gOywsCDrqZTsi5zsp4Ag7KCc7Jm4KSDtlZwg7KSE7J2EIOuvuOumrOuztOq4sOuhnC4iIiIKICAgIG1zZ3MgPSAoZGF0YSBvciB7fSkuZ2V0KCJtZXNzYWdlcyIpIG9yIFtdCiAgICBmb3IgbSBpbiBtc2dzOgogICAgICAgIGlmIGlzaW5zdGFuY2UobSwgZGljdCkgYW5kIG0uZ2V0KCJyb2xlIikgPT0gInVzZXIiOgogICAgICAgICAgICBjID0gc3RyKG0uZ2V0KCJjb250ZW50IiwgIiIpKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIGMuc3RhcnRzd2l0aCgiW+yngeyghCDsvZTrk5wg7Iuk7ZaJIOqysOqzvCIpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgbGluZXMgPSBjLnNwbGl0bGluZXMoKQogICAgICAgICAgICBpZiBsaW5lcyBhbmQgbGluZXNbMF06CiAgICAgICAgICAgICAgICByZXR1cm4gbGluZXNbMF1bOjQwXQogICAgcmV0dXJuICIo67mIIOyEuOyFmCkiCgoKZGVmIGhhbmRsZV90dXJuKG1zZywgbWVzc2FnZXMsIGFwaV9iYXNlLCBtb2RlbCwgbnVtX2N0eCwgbnVtX3ByZWRpY3QsIHdvcmtzcGFjZSwgb3V0KToKICAgIG1lc3NhZ2VzLmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogbXNnfSkKICAgIG91dC53cml0ZSgiW+yymOumrCDspJEuLi5dXG4iKQogICAgb3V0LmZsdXNoKCkKICAgIHRyeToKICAgICAgICAjIOuqqOuNuOyXkOuKlCDstZzqt7wg7LC966eMIOyghOuLrCjsu6jthY3siqTtirgg67O07Zi4KSwgbWVzc2FnZXMg7JuQ67O47J2AIOyghOyytCDrs7TsobQo7JiB7IaNL+uzteybkOyaqSkKICAgICAgICBjb250ZW50ID0gb2xsYW1hX2NoYXQoYXBpX2Jhc2UsIG1vZGVsLCBfdHJpbV9oaXN0b3J5KG1lc3NhZ2VzKSwgbnVtX2N0eCwgbnVtX3ByZWRpY3QpCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgb3V0LndyaXRlKCJb66qo6424IO2YuOy2nCDsi6TtjKhdICIgKyByZXByKGUpICsgIlxuIikKICAgICAgICBtZXNzYWdlcy5wb3AoKQogICAgICAgIHJldHVybgoKICAgIGNvbnRlbnQgPSBzdHJpcF90aGluayhjb250ZW50KQogICAgaWYgbm90IGNvbnRlbnQ6CiAgICAgICAgb3V0LndyaXRlKCJb67mIIOydkeuLtV0g66qo64247J20IOyVhOustCDrgrTsmqnrj4Qg67CY7ZmY7ZWY7KeAIOyViuyVmOyKteuLiOuLpC5cbiIpCiAgICAgICAgbWVzc2FnZXMuYXBwZW5kKHsicm9sZSI6ICJhc3Npc3RhbnQiLCAiY29udGVudCI6ICIo67mIIOydkeuLtSkifSkKICAgICAgICByZXR1cm4KCiAgICBsYW5nLCBjb2RlLCBwcmUgPSBleHRyYWN0X2ZpcnN0X2NvZGVfYmxvY2soY29udGVudCkKICAgIG1lc3NhZ2VzLmFwcGVuZCh7InJvbGUiOiAiYXNzaXN0YW50IiwgImNvbnRlbnQiOiBjb250ZW50fSkKCiAgICBpZiBwcmU6CiAgICAgICAgb3V0LndyaXRlKHByZSArICJcbiIpCgogICAgaWYgY29kZSBpcyBOb25lOgogICAgICAgIGlmIG5vdCBwcmU6CiAgICAgICAgICAgIG91dC53cml0ZShjb250ZW50LnN0cmlwKCkgKyAiXG4iKQogICAgICAgIHJldHVybgoKICAgIGNvZGUgPSBjb2RlLnN0cmlwKCJcbiIpCiAgICBvdXQud3JpdGUoIuKUgOKUgOKUgCDsi6Ttlokg7L2U65OcIOKUgOKUgOKUgFxuIikKICAgIG91dC53cml0ZShjb2RlLnJzdHJpcCgpICsgIlxuIikKICAgIG91dC53cml0ZSgi4pSA4pSA4pSAIOyLpO2WiSDqsrDqs7wg4pSA4pSA4pSAXG4iKQogICAgb3V0LmZsdXNoKCkKCiAgICByZXN1bHQsIHJjID0gcnVuX2NvZGUobGFuZywgY29kZSwgd29ya3NwYWNlKQogICAgb3V0LndyaXRlKHJlc3VsdCArICJcbiIpCgogICAgIyDri6TsnYwg7YS07J20IOyngeyghCDsi6Ttlokg6rKw6rO866W8IOyVjCDsiJgg7J6I64+E66GdIO2ZmOulmCAo6rSA7LCwKQogICAgb2JzID0gIlvsp4HsoIQg7L2U65OcIOyLpO2WiSDqsrDqs7wgKHJjPSVkKV1cbiVzIiAlIChyYywgcmVzdWx0KQogICAgbWVzc2FnZXMuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiBvYnN9KQoKCmRlZiBtYWluKCk6CiAgICBhcCA9IGFyZ3BhcnNlLkFyZ3VtZW50UGFyc2VyKCkKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1tb2RlbCIsIHJlcXVpcmVkPVRydWUpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tYXBpX2Jhc2UiLCByZXF1aXJlZD1UcnVlKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLWNvbnRleHRfd2luZG93IiwgdHlwZT1pbnQsIGRlZmF1bHQ9NDA5NikKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1tYXhfdG9rZW5zIiwgdHlwZT1pbnQsIGRlZmF1bHQ9NTEyKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLXN5c3RlbV9tZXNzYWdlIiwgZGVmYXVsdD0iIikKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1hdXRvX3J1biIsIGFjdGlvbj0ic3RvcmVfdHJ1ZSIpCiAgICBhcmdzLCBfdW5rbm93biA9IGFwLnBhcnNlX2tub3duX2FyZ3MoKQoKICAgIG1vZGVsID0gYXJncy5tb2RlbAogICAgZm9yIHByZWYgaW4gKCJvbGxhbWFfY2hhdC8iLCAib2xsYW1hLyIpOgogICAgICAgIGlmIG1vZGVsLnN0YXJ0c3dpdGgocHJlZik6CiAgICAgICAgICAgIG1vZGVsID0gbW9kZWxbbGVuKHByZWYpOl0KICAgICAgICAgICAgYnJlYWsKCiAgICBudW1fY3R4ID0gYXJncy5jb250ZXh0X3dpbmRvdyBvciA0MDk2CiAgICAjIOy9lOuTnCDruJTroZ3snbQg7J6Y66as7KeAIOyViuqyjCDstqnrtoTtnogsIOq3uOufrOuCmCDssqsg67iU66Gd66eMIOyLpO2Wie2VmOuvgOuhnCDtj63so7wg66y07ZW0CiAgICBudW1fcHJlZGljdCA9IG1heChhcmdzLm1heF90b2tlbnMgb3IgMCwgMjA0OCkKCiAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRlbnQiOiBMRUFOX1NZU1RFTX1dCgogICAgb3V0ID0gc3lzLnN0ZG91dAogICAgb3V0LndyaXRlKCJb7JeQ7J207KCE7Yq4IOykgOu5hOuQqF0g66mU7Iuc7KeA66W8IOyeheugpe2VmOyEuOyalC4gKE1JTklMT09QX3YyKVxuIikKICAgIG91dC5mbHVzaCgpCgogICAgIyDilIDilIAg7JiB7IaNIOyEuOyFmCDshKTsoJUgKEFHRU5UX1NUQVRFX0RJUiDsnojsnYQg65WM66eMKSDilIDilIAKICAgIHNlc3Npb25fZmlsZSA9ICIiCiAgICBzZXNzaW9uX3RpdGxlID0gIiIKICAgIHNlc3Npb25fY3JlYXRlZCA9IF9ub3dfaXNvKCkKICAgIGlmIFNUQVRFX0RJUjoKICAgICAgICAjIE1JTklMT09QX3YyOiDsi5zsnpEg7IucICfsnbTslrTqsIDquLAnIOyXhuydtCDtla3sg4Eg7IOIIOyEuOyFmCAo7IS47IWYIOuCtCDquLDslrXsnYAg7Jyg7KeAKQogICAgICAgIHRyeToKICAgICAgICAgICAgb3MubWFrZWRpcnMoU1RBVEVfRElSLCBleGlzdF9vaz1UcnVlKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgICAgICBzZXNzaW9uX2ZpbGUgPSBvcy5wYXRoLmpvaW4oU1RBVEVfRElSLCAic2Vzc2lvbl8lcy5qc29uIiAlIF9uZXdfc2lkKCkpCiAgICAgICAgb3V0LndyaXRlKCJb7IOIIOyEuOyFmCDsi5zsnpFdICAoL25ldyDsg4gg64yA7ZmUIMK3IC9yZW5hbWUgPOydtOumhD4g7J2066aE67OA6rK9KVxuIikKCiAgICBvdXQud3JpdGUoIj4gIikKICAgIG91dC5mbHVzaCgpCgogICAgZGVmIF9wZXJzaXN0KCk6CiAgICAgICAgaWYgbm90IHNlc3Npb25fZmlsZToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgc2lkID0gb3MucGF0aC5zcGxpdGV4dChvcy5wYXRoLmJhc2VuYW1lKHNlc3Npb25fZmlsZSkpWzBdCiAgICAgICAgc2lkID0gc2lkW2xlbigic2Vzc2lvbl8iKTpdIGlmIHNpZC5zdGFydHN3aXRoKCJzZXNzaW9uXyIpIGVsc2Ugc2lkCiAgICAgICAgX3NhdmVfc2Vzc2lvbihzZXNzaW9uX2ZpbGUsIHsKICAgICAgICAgICAgImlkIjogc2lkLAogICAgICAgICAgICAia2luZCI6IFNUQVRFX0tJTkQsCiAgICAgICAgICAgICJtb2RlbCI6IG1vZGVsLAogICAgICAgICAgICAid29ya3NwYWNlIjogV09SS1NQQUNFLAogICAgICAgICAgICAidGl0bGUiOiBzZXNzaW9uX3RpdGxlLAogICAgICAgICAgICAiY3JlYXRlZCI6IHNlc3Npb25fY3JlYXRlZCwKICAgICAgICAgICAgInVwZGF0ZWQiOiBfbm93X2lzbygpLAogICAgICAgICAgICAibWVzc2FnZXMiOiBtZXNzYWdlcywKICAgICAgICB9KQoKICAgIHdoaWxlIFRydWU6CiAgICAgICAgbGluZSA9IHN5cy5zdGRpbi5yZWFkbGluZSgpCiAgICAgICAgaWYgbGluZSA9PSAiIjoKICAgICAgICAgICAgYnJlYWsKICAgICAgICBtc2cgPSBsaW5lLnN0cmlwKCkKICAgICAgICBpZiBub3QgbXNnOgogICAgICAgICAgICBvdXQud3JpdGUoIj4gIikKICAgICAgICAgICAgb3V0LmZsdXNoKCkKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiBtc2cubG93ZXIoKSBpbiAoImV4aXQiLCAicXVpdCIsICIvZXhpdCIsICIvcXVpdCIpOgogICAgICAgICAgICBicmVhawogICAgICAgIF9sb3cgPSBtc2cubG93ZXIoKQogICAgICAgIGlmIF9sb3cgaW4gKCIvbmV3IiwgIi9jbGVhciIsICIvcmVzZXQiKToKICAgICAgICAgICAgbWVzc2FnZXMgPSBbeyJyb2xlIjogInN5c3RlbSIsICJjb250ZW50IjogTEVBTl9TWVNURU19XQogICAgICAgICAgICBzZXNzaW9uX2NyZWF0ZWQgPSBfbm93X2lzbygpCiAgICAgICAgICAgIHNlc3Npb25fdGl0bGUgPSAiIgogICAgICAgICAgICBpZiBTVEFURV9ESVI6CiAgICAgICAgICAgICAgICBzZXNzaW9uX2ZpbGUgPSBvcy5wYXRoLmpvaW4oU1RBVEVfRElSLCAic2Vzc2lvbl8lcy5qc29uIiAlIF9uZXdfc2lkKCkpCiAgICAgICAgICAgIG91dC53cml0ZSgiW+q4sOyWtSDsgq3soJzrkKgg4oCUIOyDiCDrjIDtmZQg7Iuc7J6RXVxuPiAiKQogICAgICAgICAgICBvdXQuZmx1c2goKQogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIF9sb3cuc3RhcnRzd2l0aCgiL3JlbmFtZSIpOgogICAgICAgICAgICBfbmV3bmFtZSA9IG1zZ1tsZW4oIi9yZW5hbWUiKTpdLnN0cmlwKCkKICAgICAgICAgICAgaWYgbm90IF9uZXduYW1lOgogICAgICAgICAgICAgICAgb3V0LndyaXRlKCLsgqzsmqnrspU6IC9yZW5hbWUgPOyDiCDsnbTrpoQ+XG4+ICIpCiAgICAgICAgICAgICAgICBvdXQuZmx1c2goKQogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgc2Vzc2lvbl90aXRsZSA9IF9uZXduYW1lCiAgICAgICAgICAgIF9wZXJzaXN0KCkKICAgICAgICAgICAgb3V0LndyaXRlKCJb7J2066aEIOuzgOqyveuQqDogIiArIF9uZXduYW1lICsgIl1cbj4gIikKICAgICAgICAgICAgb3V0LmZsdXNoKCkKICAgICAgICAgICAgY29udGludWUKICAgICAgICB0cnk6CiAgICAgICAgICAgIGhhbmRsZV90dXJuKG1zZywgbWVzc2FnZXMsIGFyZ3MuYXBpX2Jhc2UsIG1vZGVsLAogICAgICAgICAgICAgICAgICAgICAgICBudW1fY3R4LCBudW1fcHJlZGljdCwgV09SS1NQQUNFLCBvdXQpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgICAgICBvdXQud3JpdGUoIlxuW+yYpOulmF0g7YS0IOyymOumrCDsi6TtjKg6ICIgKyByZXByKGUpICsgIlxuIikKICAgICAgICAgICAgdHJhY2ViYWNrLnByaW50X2V4YyhmaWxlPW91dCkKICAgICAgICBfcGVyc2lzdCgpCiAgICAgICAgb3V0LndyaXRlKCJcbj4gIikKICAgICAgICBvdXQuZmx1c2goKQogICAgcmV0dXJuIDAKCgppZiBfX25hbWVfXyA9PSAiX19tYWluX18iOgogICAgc3lzLmV4aXQobWFpbigpKQo="
_AGENT_REPL_BOOTSTRAP = "import os,base64;exec(base64.b64decode(os.environ['AGENT_REPL_SRC']).decode('utf-8'))"
# <<< LLM_AGENT_REPL_FIX_v1

def _llm_session_log_dir():
    """에이전트 로그를 llm_environment/logs 아래로 강제 (cwd 오염 방지)."""
    import os
    from pathlib import Path
    ov = os.environ.get("LLM_ENV_DIR")
    if ov:
        b = Path(ov)
        d = b / "logs" if b.name != "logs" else b
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return d
    try:
        here = Path(__file__).resolve()
        cands = [here.parent] + list(here.parents)
    except Exception:
        cands = [Path.cwd()]
    for c in cands:
        try:
            if (c / "llm_environment").is_dir() or (c / "RUN.bat").exists() or (c / "INSTALL.bat").exists():
                d = c / "llm_environment" / "logs"
                d.mkdir(parents=True, exist_ok=True)
                return d
        except Exception:
            continue
    d = Path.cwd() / "llm_environment" / "logs"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d
# <<< LLM_SESSION_LOG_PATH_FIX_v1
import os
import queue
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional


# ─────────────────────────────────────────────
#  메시지 종류 (큐에 흐르는 이벤트)
# ─────────────────────────────────────────────
LEVEL_STDOUT = "stdout"
LEVEL_STDERR = "stderr"
LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_ERROR = "error"
LEVEL_TERMINATED = "terminated"


@dataclass
class AgentMessage:
    """에이전트 → GUI 로 흘러가는 단일 이벤트."""
    level: str  # LEVEL_*
    text: str
    timestamp: float = field(default_factory=time.time)


# ─────────────────────────────────────────────
#  ErrorGuard — 위험 패턴 사전 차단
# ─────────────────────────────────────────────
_VISION_PATTERNS = [
    re.compile(r"\bscreenshot\b", re.IGNORECASE),
    re.compile(r"\bscreen[\s_-]*capture\b", re.IGNORECASE),
    re.compile(r"\bpyautogui\b", re.IGNORECASE),
    re.compile(r"\bpynput\b", re.IGNORECASE),
    re.compile(r"PIL\.ImageGrab", re.IGNORECASE),
    re.compile(r"\bImageGrab\b", re.IGNORECASE),
    re.compile(r"\b(?:from\s+mss\s+import|import\s+mss|mss\.mss)\b", re.IGNORECASE),
    re.compile(r"computer\.(display|mouse|keyboard|screen)", re.IGNORECASE),
    re.compile(r"\bget_monitors\b", re.IGNORECASE),
    re.compile(r"\bos_mode\b", re.IGNORECASE),
]


def looks_like_vision_attempt(line: str) -> bool:
    """에이전트가 화면 캡처/GUI 자동화를 시도하는 패턴인지 감지.

    Returns True if the line matches any known vision/GUI automation pattern.
    """
    for pat in _VISION_PATTERNS:
        if pat.search(line):
            return True
    return False


# ─────────────────────────────────────────────
#  UnifiedAgent — 메인 객체
# ─────────────────────────────────────────────
# >>> LLM_VERBOSE_LOG_v1 (PATCH_VERBOSE_LOG.py) - 로그 상세화 + on/off 토글
import json as _json_vlog
import time as _time_vlog
from pathlib import Path as _Path_vlog

_VLOG_CACHE = {"val": None, "ts": 0.0}


def _vlog_config_path():
    """launcher/settings/user_config.json (agent_runner.py 의 부모 = launcher/)."""
    try:
        return _Path_vlog(__file__).resolve().parent / "settings" / "user_config.json"
    except Exception:
        return None


def logging_enabled() -> bool:
    """세부 로그 on/off. user_config.json 'logging_enabled' (기본 True). 2초 캐시."""
    now = _time_vlog.time()
    if _VLOG_CACHE["val"] is not None and (now - _VLOG_CACHE["ts"]) < 2.0:
        return _VLOG_CACHE["val"]
    val = True
    try:
        p = _vlog_config_path()
        if p and p.exists():
            data = _json_vlog.loads(p.read_text(encoding="utf-8"))
            val = bool(data.get("logging_enabled", True))
    except Exception:
        val = True
    _VLOG_CACHE["val"] = val
    _VLOG_CACHE["ts"] = now
    return val


def set_logging_enabled(enabled: bool) -> bool:
    """user_config.json 의 logging_enabled 설정. 성공 시 True."""
    try:
        p = _vlog_config_path()
        if not p:
            return False
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if p.exists():
            try:
                data = _json_vlog.loads(p.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data["logging_enabled"] = bool(enabled)
        p.write_text(_json_vlog.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        _VLOG_CACHE["val"] = None
        return True
    except Exception:
        return False
# <<< LLM_VERBOSE_LOG_v1


class UnifiedAgent:
    """subprocess.PIPE 기반 에이전트 실행기.

    사용:
        agent = UnifiedAgent()
        agent.start(cmd=["docker", "run", ...], env={...})
        # 폴링 (GUI 메인 루프에서 100ms 마다)
        for msg in agent.drain_messages():
            chat_panel.append(msg.level, msg.text)
        # 사용자 입력
        agent.send_input("hello")
        # 종료
        agent.stop(timeout=3.0)

    Thread-safety: 모든 public 메서드는 어느 스레드에서나 호출 가능.
    """

    def __init__(self, max_queue: int = 10000):
        self._proc: Optional[subprocess.Popen] = None
        self._cmd: List[str] = []
        self._messages: queue.Queue = queue.Queue(maxsize=max_queue)
        self._input_queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._readers: List[threading.Thread] = []
        self._writer: Optional[threading.Thread] = None
        self._error_guard_enabled = True
        # v6_lifelog: 컨테이너명과 세션 로그 파일 핸들
        self._container_name_v6 = None
        self._session_log_v6 = None
        # v4_lifecycle: 컨테이너명 (cmd 에서 --name 파싱하여 채움)
        self._container_name: Optional[str] = None
        # v4_lifecycle: 디버그 로그 파일 핸들 (선택적)
        self._debug_log_fh = None
        # v4_lifecycle: 첫 stdout 수신 시각 (TTFT 측정용)
        self._first_output_at: Optional[float] = None

    # ── lifecycle ──
    def is_running(self) -> bool:
        """에이전트 프로세스가 살아있는지."""
        with self._lock:
            if self._proc is None:
                return False
            return self._proc.poll() is None

    def start(
        self,
        cmd: List[str],
        env: Optional[dict] = None,
        cwd: Optional[Path] = None,
    ) -> bool:
        """에이전트 시작.

        Args:
            cmd: 실행할 명령 (예: ["docker", "run", "-i", ...])
                 IMPORTANT: docker run 의 경우 -t 빼고 -i 만 줘야 PIPE 가 동작.
            env: 환경변수 (None 이면 부모 env 상속)
            cwd: 작업 디렉터리

        Returns:
            True if started, False if already running.
        """
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return False
            self._cmd = list(cmd)
            self._stopped.clear()

            # v4_lifecycle: cmd 에서 --name <X> 자동 추출
            self._container_name = None
            try:
                _idx = self._cmd.index('--name')
                if _idx + 1 < len(self._cmd):
                    self._container_name = self._cmd[_idx + 1]
            except ValueError:
                pass

            # v4_lifecycle: 디버그 로그 파일 오픈 (best-effort)
            try:
                from . import config as _cfg
                _log_dir = Path(_cfg.ENV_PATH) / 'logs' if hasattr(_cfg, 'ENV_PATH') else Path('.')
                _log_dir.mkdir(parents=True, exist_ok=True)
                _ts = time.strftime('%Y%m%d_%H%M%S')
                _name_part = self._container_name or 'agent'
                self._debug_log_fh = open(
                    str(_llm_session_log_dir() / ('agent_runner_' + _name_part + '_' + _ts + '.log')),
                    'w', encoding='utf-8'
                )
                self._debug_log_fh.write(
                    "[start] " + time.strftime("%H:%M:%S")
                    + " container=" + str(self._container_name) + "\n"
                )
                self._debug_log_fh.write(
                    "[cmd] " + " ".join(self._cmd[:8]) + " ...\n"
                )
                self._debug_log_fh.flush()
            except Exception:
                self._debug_log_fh = None

            # Windows 에서 CREATE_NO_WINDOW — 콘솔창 안 뜨도록
            popen_kwargs = {
                "stdin": subprocess.PIPE,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "bufsize": 1,  # line-buffered
                "universal_newlines": True,
                "encoding": "utf-8",
                "errors": "replace",
            }
            if env is not None:
                popen_kwargs["env"] = env
            if cwd is not None:
                popen_kwargs["cwd"] = str(cwd)
            if os.name == "nt":
                popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

            try:
                self._proc = subprocess.Popen(cmd, **popen_kwargs)
            except FileNotFoundError as e:
                self._emit(LEVEL_ERROR, f"명령을 찾을 수 없습니다: {e}")
                self._proc = None
                return False
            except Exception as e:
                self._emit(LEVEL_ERROR, f"에이전트 시작 실패: {type(e).__name__}: {e}")
                self._proc = None
                return False

            # ── 백그라운드 스레드 기동 ──
            self._readers = [
                threading.Thread(
                    target=self._reader_loop,
                    args=(self._proc.stdout, LEVEL_STDOUT),
                    daemon=True, name="agent-stdout",
                ),
                threading.Thread(
                    target=self._reader_loop,
                    args=(self._proc.stderr, LEVEL_STDERR),
                    daemon=True, name="agent-stderr",
                ),
            ]
            for t in self._readers:
                t.start()

            self._writer = threading.Thread(
                target=self._writer_loop,
                daemon=True, name="agent-stdin",
            )
            self._writer.start()

            # 종료 감지 스레드
            threading.Thread(
                target=self._wait_loop,
                daemon=True, name="agent-wait",
            ).start()

            # v6_lifelog: 세션 로그 + 컨테이너명 추출 + cleanup 등록
            self._container_name_v6 = None
            try:
                _idx = self._cmd.index("--name")
                if _idx + 1 < len(self._cmd):
                    self._container_name_v6 = self._cmd[_idx + 1]
            except (ValueError, AttributeError):
                pass
            self._session_log_v6 = None
            try:
                from . import lifelog as _ll
                _name = self._container_name_v6 or ("agent_pid" + str(self._proc.pid))
                self._session_log_v6 = _ll.open_session_log(_name)
                _ll.log("INFO", "에이전트 시작 (PID=" + str(self._proc.pid)
                       + ", container=" + str(self._container_name_v6) + ")")
                _ll.log_session(self._session_log_v6, "INFO",
                                "cmd=" + " ".join(self._cmd[:10]) + " ...")
                # 자기 자신을 cleanup 에 등록 — 종료 hook 에서 자동 정리
                _self_ref = self
                _ll.register_cleanup(lambda: _self_ref.stop(timeout=2.0))
            except Exception as _le:
                pass
            self._emit(LEVEL_INFO, f"에이전트 시작 (PID={self._proc.pid})")
            if self._container_name:
                self._emit(LEVEL_INFO, f"컨테이너: {self._container_name}")
            # v4_lifecycle: 활성 에이전트 registry 등록
            try:
                from . import agent_lifecycle as _lc
                _lc.register(self)
            except Exception as _e:
                self._emit(LEVEL_WARN, f"lifecycle 등록 실패: {_e}")
            return True

    def stop(self, timeout: float = 3.0) -> None:
        """에이전트 종료 — graceful 후 forceful.

        Args:
            timeout: graceful 종료 대기 시간 (초)
        """
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._stopped.set()
                return

            # 1) stdin 닫기 — exit 신호
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.close()
            except Exception:
                pass

            # 2) terminate
            try:
                proc.terminate()
            except Exception:
                pass

        # 3) 대기
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except Exception:
                pass

        # v4_lifecycle: docker 컨테이너 강제 종료 (CLI 래퍼만 죽이는 것 방지)
        if self._container_name:
            try:
                _no_window = {}
                if os.name == "nt":
                    _no_window["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
                subprocess.run(
                    ["docker", "stop", "-t", "2", self._container_name],
                    capture_output=True, timeout=5, **_no_window
                )
                subprocess.run(
                    ["docker", "rm", "-f", self._container_name],
                    capture_output=True, timeout=5, **_no_window
                )
                self._emit(LEVEL_INFO, f"컨테이너 정리: {self._container_name}")
            except Exception as _e:
                self._emit(LEVEL_WARN, f"컨테이너 정리 실패: {_e}")

        # v4_lifecycle: 디버그 로그 종료
        if self._debug_log_fh is not None:
            try:
                self._debug_log_fh.write(
                    "[stop] " + time.strftime("%H:%M:%S")
                    + " container=" + str(self._container_name) + "\n"
                )
                self._debug_log_fh.close()
            except Exception:
                pass
            self._debug_log_fh = None

        # v4_lifecycle: lifecycle registry 에서 제거
        try:
            from . import agent_lifecycle as _lc
            _lc.unregister(self)
        except Exception:
            pass

        # v6_lifelog: 컨테이너 강제 격멸 (docker stop -> docker kill fallback)
        _container = getattr(self, "_container_name_v6", None)
        if _container:
            try:
                from . import lifelog as _ll
                _ll.force_kill_container(_container, timeout=2)
            except Exception as _le:
                self._emit(LEVEL_WARN, "force_kill 예외: " + str(_le))

        # v6_lifelog: 세션 로그 close (마지막 flush 보장)
        _fh = getattr(self, "_session_log_v6", None)
        if _fh is not None:
            try:
                from . import lifelog as _ll
                _ll.log_session(_fh, "INFO", "===== 에이전트 종료 =====")
                _fh.close()
            except Exception:
                pass
            self._session_log_v6 = None

        self._stopped.set()
        self._emit(LEVEL_WARN, "에이전트 종료됨")

    def send_input(self, line: str) -> bool:
        """사용자 입력을 에이전트 stdin 에 보냄.

        Returns False if agent isn't running.
        """
        if not self.is_running():
            return False
        if not line.endswith("\n"):
            line = line + "\n"
        try:
            self._input_queue.put_nowait(line)
            return True
        except queue.Full:
            self._emit(LEVEL_WARN, "입력 큐 가득참 — 메시지 버려짐")
            return False

    def drain_messages(self, max_n: int = 200) -> List[AgentMessage]:
        """큐에서 메시지를 비파괴적으로 비움. GUI 가 폴링으로 호출.

        Returns up to `max_n` messages, oldest first. Empty list if no messages.
        """
        out: List[AgentMessage] = []
        for _ in range(max_n):
            try:
                msg = self._messages.get_nowait()
            except queue.Empty:
                break
            out.append(msg)
        return out

    # ── 내부 ──
    def _emit(self, level: str, text: str) -> None:
        """메시지를 큐에 넣음 — 가득 차면 가장 오래된 것 버림."""
        msg = AgentMessage(level=level, text=text)
        try:
            self._messages.put_nowait(msg)
        except queue.Full:
            # 가장 오래된 항목 하나 버리고 재시도
            try:
                self._messages.get_nowait()
            except queue.Empty:
                pass
            try:
                self._messages.put_nowait(msg)
            except queue.Full:
                pass  # 어쩔 수 없음

    def _read_realtime(self, stream):
        """v7.9: 문자 단위 실시간 읽기. readline 블록 회피.

        - 완성된 줄은 \\n 기준 즉시 방출
        - Open Interpreter 프롬프트('> ', '>>> ')는 줄바꿈 없이도 즉시 방출
        호출측(_reader_loop)의 줄 처리 로직을 그대로 재사용한다.
        """
        _PROMPTS = ("> ", ">>> ")
        _buf = []
        while True:
            try:
                ch = stream.read(1)
            except (ValueError, OSError):
                break
            if ch == "":
                break
            if ch == "\n":
                yield "".join(_buf) + "\n"
                _buf = []
                continue
            _buf.append(ch)
            if "".join(_buf) in _PROMPTS:
                yield "".join(_buf)
                _buf = []
        if _buf:
            yield "".join(_buf)

    def _reader_loop(self, stream, level: str) -> None:
        """stdout/stderr 한 줄씩 읽어 큐에 push.

        ErrorGuard: vision 시도 패턴 감지 시 WARN 추가.
        """
        try:
            for raw_line in self._read_realtime(stream):
                line = raw_line.rstrip("\n\r")
                if not line:
                    # 빈 줄도 표시 (코드 블록 보존)
                    self._emit(level, "")
                    continue

                # v4_lifecycle: 디버그 로그 + 첫 토큰 시각 측정
                if self._debug_log_fh is not None:
                    try:
                        self._debug_log_fh.write(
                            "[" + level + "] " + line + "\n"
                        )
                        self._debug_log_fh.flush()
                    except Exception:
                        pass
                if self._first_output_at is None and level == LEVEL_STDOUT:
                    self._first_output_at = time.time()
                # v6_lifelog + LLM_VERBOSE_LOG_v1: 세션 로그 (on/off 토글)
                try:
                    _fh = getattr(self, "_session_log_v6", None)
                    if _fh is not None and logging_enabled():
                        from . import lifelog as _ll
                        _ll.log_session(_fh, level.upper(), line)
                except Exception:
                    pass
                # ErrorGuard
                if self._error_guard_enabled and looks_like_vision_attempt(line):
                    self._emit(
                        LEVEL_WARN,
                        f"⚠ 화면 캡처/GUI 자동화 패턴 감지됨 — 무시됨: {line[:80]}",
                    )

                self._emit(level, line)
        except (ValueError, OSError):
            # 스트림이 닫힌 정상 종료
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    def _writer_loop(self) -> None:
        """입력 큐에서 한 줄씩 꺼내 에이전트 stdin 에 씀."""
        while not self._stopped.is_set():
            try:
                line = self._input_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            with self._lock:
                proc = self._proc
                if proc is None or proc.stdin is None or proc.stdin.closed:
                    break
                try:
                    proc.stdin.write(line)
                    proc.stdin.flush()
                    _txt = line.rstrip("\n\r")
                    _dbg = getattr(self, "_debug_log_fh", None)
                    if _dbg is not None:
                        try:
                            _dbg.write("[stdin] " + _txt + "\n")
                            _dbg.flush()
                        except Exception:
                            pass
                    # LLM_VERBOSE_LOG_v1: 사용자 입력을 세션 로그에도 (턴 번호 + 빈입력 경고)
                    try:
                        _fh = getattr(self, "_session_log_v6", None)
                        if _fh is not None and logging_enabled():
                            _n = getattr(self, "_vlog_turn", 0) + 1
                            setattr(self, "_vlog_turn", _n)
                            from . import lifelog as _ll
                            _ll.log_session(_fh, "INFO", "----- 사용자 입력 #" + str(_n) + " -----")
                            if _txt == "":
                                _ll.log_session(_fh, "WARN", "[stdin] (빈 입력!) - 모델에 빈 메시지 전달됨")
                            else:
                                _ll.log_session(_fh, "STDIN", _txt)
                    except Exception:
                        pass
                except (BrokenPipeError, OSError, ValueError):
                    break

    def _wait_loop(self) -> None:
        """에이전트 종료를 감지해 TERMINATED 메시지 emit."""
        proc = self._proc
        if proc is None:
            return
        try:
            rc = proc.wait()
        except Exception:
            rc = -1
        self._stopped.set()
        self._emit(LEVEL_TERMINATED, f"프로세스 종료 (rc={rc})")


# ─────────────────────────────────────────────
#  명령 조립 헬퍼 — agent_chat 액션에서 사용
# ─────────────────────────────────────────────
def build_sandbox_pipe_cmd(
    image: str,
    container_name: str,
    workspace: Path,
    workspace_mount: str,
    model_tag: str,
    ollama_port: int,
    profile_system_message: str,
    context_window: int = 4096,
    memory_limit: Optional[str] = None,
    cpu_limit: Optional[str] = None,
    block_internet: bool = True,
    auto_run: bool = False,  # v5_runaway: 무한 도구 루프 차단
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """GUI-통합 모드용 docker run 명령 조립.

    중요한 차이점 (vs agent_sandbox._build_command):
        - `-t` (tty) 없음 — PIPE 모드용
        - `-i` (stdin) 있음 — 사용자 입력
        - `--rm` 자동 정리
        - --no_vision 안전장치 (system_message + env var)

    Args:
        profile_system_message: 프로필별 system 메시지 (영어)
        block_internet: True 면 --dns=0.0.0.0
        auto_run: True 면 --auto_run 추가 (샌드박스 안이라 안전)
    """
    # >>> AGENT_STATE_PERSIST_v1 (영속 세션 마운트; 자동 삽입)
    _state_mount = []
    _state_env = []
    try:
        from . import user_data as _ud
        _sh = str(_ud.interpreter_dir("sandbox"))
        _state_mount = ["-v", _sh + ":/home/agent/.agent_state"]
        _state_env = ["-e", "AGENT_STATE_DIR=/home/agent/.agent_state",
                      "-e", "AGENT_STATE_KIND=sandbox"]
    except Exception:
        _state_mount = []
        _state_env = []
    # <<< AGENT_STATE_PERSIST_v1
    cmd = [
        "docker", "run", "--rm", "-i",  # -t 없음!
        "--name", container_name,
        "-v", f"{workspace}:{workspace_mount}",
        "--add-host=host.docker.internal:host-gateway",
        # ErrorGuard: 환경변수로 vision 비활성 표시
        "-e", "DISABLE_VISION=1",
        "-e", "NO_DISPLAY=1",
        "-e", "DISPLAY=",  # 빈 값 — vision 라이브러리들이 fail-fast
        # v5_runaway: Python stdout 즉시 flush (block buffering 해소)
        "-e", "PYTHONUNBUFFERED=1",
        # v5_runaway: LiteLLM banner / 트레이닝 광고 메시지 억제
        "-e", "LITELLM_LOG=ERROR",
        "-e", "AGENT_REPL_SRC=" + _AGENT_REPL_SRC_B64,
    ]
    cmd += _state_mount + _state_env  # AGENT_STATE_PERSIST_v1

    # FOLDER_POLICY_v1: 상시 허용 폴더 마운트 (샌드박스는 그 외 경로 물리 차단)
    try:
        try:
            from .. import folder_policy as _fp
        except Exception:
            from launcher import folder_policy as _fp
        for _h, _c in _fp.mounts_for():
            cmd += ["-v", _h + ":" + _c]
        # FOLDER_POLICY_OVERLAY_v1: 허용 상위 안의 '금지' 하위를 빈 tmpfs 로 가림
        if hasattr(_fp, "tmpfs_masks_for"):
            for _m in _fp.tmpfs_masks_for():
                cmd += ["--tmpfs", _m]
    except Exception:
        pass

    if block_internet:
        cmd += ["--dns=0.0.0.0"]
    if cpu_limit:
        cmd += [f"--cpus={cpu_limit}"]
    if memory_limit:
        cmd += [f"--memory={memory_limit}"]

    cmd += [
        image, "python3", "-c", _AGENT_REPL_BOOTSTRAP,
        "--model", f"ollama/{model_tag}",
        "--api_base", f"http://host.docker.internal:{ollama_port}",
        "--context_window", str(context_window),
        # v5_runaway: 응답 길이 제한 (stop 토큰 인식 실패 시 자동 cut)
        "--max_tokens", "512",
        "--system_message", profile_system_message,
    ]

    if auto_run:
        cmd += ["--auto_run"]
    if extra_args:
        cmd += list(extra_args)

    return cmd




# ─────────────────────────────────────────────
#  v7_1_unified: 호스트 직접 모드 PIPE 명령 조립
# ─────────────────────────────────────────────
def build_host_pipe_cmd(
    interpreter_exe: str,
    model_tag: str,
    ollama_url: str,
    profile_system_message: str,
    context_window: int = 4096,
    auto_run: bool = False,
    extra_args=None,
):
    """호스트 직접 모드용 interpreter 명령 조립 (PIPE 방식).

    agent_sandbox 의 build_sandbox_pipe_cmd 와 달리 docker 없이
    호스트의 interpreter.exe 를 직접 PIPE 로 실행.

    중요:
      - 컨테이너 격리 없음 (위험) — 호출자가 확인 게이트 통과 필수
      - auto_run 기본 False — 매 명령 사용자 확인 (안전)
      - PYTHONUNBUFFERED 등은 호출자가 env 로 전달

    Args:
        interpreter_exe: interpreter.exe 절대 경로
        model_tag: 모델 태그
        ollama_url: Ollama API URL (예: http://127.0.0.1:11434)
        profile_system_message: 프로필 system 메시지
        auto_run: True 면 --auto_run (위험, 기본 False)
    """
    cmd = [
        interpreter_exe,
        "--model", "ollama/" + model_tag,
        "--api_base", ollama_url,
        "--context_window", str(context_window),
        "--max_tokens", "512",
        "--system_message", profile_system_message,
    ]
    if auto_run:
        cmd += ["--auto_run"]
    if extra_args:
        cmd += list(extra_args)
    return cmd


__all__ = [
    "AgentMessage",
    "UnifiedAgent",
    "build_sandbox_pipe_cmd",
    "build_host_pipe_cmd",
    "looks_like_vision_attempt",
    "LEVEL_STDOUT", "LEVEL_STDERR", "LEVEL_INFO",
    "LEVEL_WARN", "LEVEL_ERROR", "LEVEL_TERMINATED",
]
