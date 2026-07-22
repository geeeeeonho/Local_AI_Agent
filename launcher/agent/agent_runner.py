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
_AGENT_REPL_SRC_B64 = "IyEvdXNyL2Jpbi9lbnYgcHl0aG9uMwojIC0qLSBjb2Rpbmc6IHV0Zi04IC0qLQojIGFnZW50X3JlcGwucHkgKHY5LjMsIE1JTklMT09QX3YxKQojIE9wZW4gSW50ZXJwcmV0ZXIg7KCc6rGwIOKAlCBPbGxhbWEgL2FwaS9jaGF0IOyngeygkSDtmLjstpwg6riw67CYICfri6jsnbwg7Iqk7YWdIOy9lOuTnCDsl5DsnbTsoITtirgnLgojCiMg7ISk6rOEICjshoztmJUg66Gc7LusIOuqqOuNuOyXkCDrp57stqQpOgojICAgLSDsp6fsnYAg7Iuc7Iqk7YWcIO2UhOuhrO2UhO2KuCAo6rec7LmZIOyghOyCrC/tlITroIjsnoTsm4ztgaztmZQg67Cp7KeAKQojICAgLSDrqqjrjbgg7J2R64u17JeQ7IScICfssqsg7L2U65OcIOu4lOuhnSDtlZjrgpgn66eMIOy2lOy2nMK37Iuk7ZaJICjrgpjrqLjsp4DripQg67KE66a8IOKGkiDtj63so7wg7LCo64uoKQojICAgLSDri6jsnbwg7Iqk7YWdOiDtlZwg7YS0ID0g66qo6424IDHtmowg7Zi47LacICsg7L2U65OcIDHtmowg7Iuk7ZaJLiDsnpDrj5kg64uk64uo6rOEIOujqO2UhCDsl4bsnYwuCiMgICAtIOyLpO2WiSDqsrDqs7zripQg64uk7J2MIO2EtCDsu6jthY3siqTtirjroZwg7ZmY66WYICjrqYDti7DthLQg7Jew7IaN7ISxIOycoOyngCkKIyAgIC0gcXdlbjMgdGhpbmtpbmcg7LCo64uoOiB0aGluaz1mYWxzZSArIDx0aGluaz4g7KCc6rGwCiMKIyBob3N0KGFnZW50X3J1bm5lcikg7Zi47ZmYIEkvTyDqs4Tslb06CiMgICAtIOyLnOyekSDsi5wgICJb7JeQ7J207KCE7Yq4IOykgOu5hOuQqF0gLi4uIiArICI+ICIKIyAgIC0g66ekIO2EtCDrgZ0gIj4gIiAgKGhvc3Qg7J2YIO2UhOuhrO2UhO2KuCBzZW50aW5lbCkKIyAgIC0gc3RkaW4g7ZWcIOykhCA9IO2VnCDrqZTsi5zsp4AKaW1wb3J0IHN5cwppbXBvcnQgb3MKaW1wb3J0IHJlCmltcG9ydCBqc29uCmltcG9ydCBhcmdwYXJzZQppbXBvcnQgc3VicHJvY2VzcwppbXBvcnQgdHJhY2ViYWNrCmltcG9ydCB1cmxsaWIucmVxdWVzdAoKdHJ5OgogICAgc3lzLnN0ZG91dC5yZWNvbmZpZ3VyZShlbmNvZGluZz0idXRmLTgiKSAgIyBweTMuNysKZXhjZXB0IEV4Y2VwdGlvbjoKICAgIHBhc3MKCldPUktTUEFDRSA9IG9zLmVudmlyb24uZ2V0KCJBR0VOVF9XT1JLU1BBQ0UiLCAiL2hvbWUvYWdlbnQvd29ya3NwYWNlIikKCiMg7JiB7IaNIOyEuOyFmCAoaG9zdCDqsIAg66eI7Jq07Yq47ZWcIO2PtOuNlCkuIOu5hOyWtCDsnojsnLzrqbQg7JiB7IaNL+uzteybkCDruYTtmZzshLEg4oCUIOq4sOyhtCDrj5nsnpHqs7wg64+Z7J28LgpTVEFURV9ESVIgPSBvcy5lbnZpcm9uLmdldCgiQUdFTlRfU1RBVEVfRElSIiwgIiIpClNUQVRFX0tJTkQgPSBvcy5lbnZpcm9uLmdldCgiQUdFTlRfU1RBVEVfS0lORCIsICJzYW5kYm94IikKCkxFQU5fU1lTVEVNID0gKAogICAgIuuLueyLoOydgCAvaG9tZS9hZ2VudC93b3Jrc3BhY2Ug7JeQ7IScIOyekeyXhe2VmOuKlCDsvZTrlKkg7JeQ7J207KCE7Yq47J6F64uI64ukLlxuIgogICAgIlxuIgogICAgIlvstpzroKUg7ZiV7IudIOKAlCDrsJjrk5zsi5wg7KeA7YKk7IS47JqUXVxuIgogICAgIi0g7IKs7Jqp7J6Q7J2YIOyalOyyreydhCDsiJjtlontlZjripQg7L2U65Oc66W8ICfsoJXtmZXtnogg7ZWY64KY7J2YIOy9lOuTnCDruJTroZ0n7Jy866Gc66eMIOy2nOugpe2VqeuLiOuLpC5cbiIKICAgICItIFB5dGhvbiDsnYAgYGBgcHl0aG9uIOy9lOuTnCBgYGAgLCDshbgg66qF66C57J2AIGBgYGJhc2gg7L2U65OcIGBgYCDtmJXsi53snLzroZwg6rCQ7IyJ64uI64ukLlxuIgogICAgIi0g7L2U65OcIOu4lOuhnSDslZ7sl5Ag66y07JeH7J2EIO2VoOyngCDtlZzqta3slrQg7ZWcIOusuOyepeunjCDsoIHsirXri4jri6Qo7ISg7YOdKS4g7L2U65OcIOu4lOuhneydgCDtlZwg7YS07JeQIO2VmOuCmOunjC5cbiIKICAgICJcbiIKICAgICJb7J6R7JeFIOybkOy5mV1cbiIKICAgICItIOyCrOyaqeyekOqwgCDsmpTssq3tlZwgJ+uwlOuhnCDqt7gg7J6R7JeFIO2VmOuCmCfrp4wg7IiY7ZaJ7ZWp64uI64ukLlxuIgogICAgIi0g7JqU7LKt7ZWY7KeAIOyViuydgCDtlITroIjsnoTsm4ztgawv7Ju57ISc67KEL+uylOyaqSDrp6Tri4jsoIAg7ZWo7IiYL+yYiOyLnCDrs7Tsnbzrn6ztlIzroIjsnbTtirgv7Iqk7LqQ7Y+065SpIOq4iOyngC5cbiIKICAgICItIOyLnOyKpO2FnCDqt5zsuZnsnYQg7L2U65Oc64KYIOyjvOyEneycvOuhnCDsmK7qsqgg7KCB7KeAIOuniOyEuOyalC5cbiIKICAgICItIOuqqOuToCDtjIzsnbzsnYAgL2hvbWUvYWdlbnQvd29ya3NwYWNlIOyVhOuemOyXkCDrp4zrk63ri4jri6QuXG4iCiAgICAiLSDtjIzsnbwg7IOd7ISxL+yImOygleydgCDshbggaGVyZWRvYyhjYXQgPDxFT0YpIOuMgOyLoCBQeXRob24gIgogICAgIm9wZW4ocGF0aCwgJ3cnLCBlbmNvZGluZz0ndXRmLTgnKS53cml0ZSguLi4pIOulvCDsgqzsmqntlZjshLjsmpQgIgogICAgIihoZXJlZG9jIOydgCDsooXro4wg7ZGc7IucIOuIhOudveycvOuhnCDrgrTsmqnsnbQg7J6Y66a964uI64ukKS5cbiIKICAgICItICfsiJjsoJUv6rWs7LK07ZmUL+yekOyEuO2eiC/snbTslrTshJwnIOyalOyyreydtOuptCDrqLzsoIAgIgogICAgIm9wZW4ocGF0aCwgZW5jb2Rpbmc9J3V0Zi04JykucmVhZCgpIOuhnCDquLDsobQg64K07Jqp7J2EIOydveqzoCwg7ZmV7J6l7ZW0IOuLpOyLnCDsoIDsnqXtlZjshLjsmpQuXG4iCiAgICAiLSDsnbQg7Luo7YWM7J2064SI64qUIOyduO2EsOuEt+ydtCDssKjri6jrkJjslrQgcGlwIGluc3RhbGwg7J20IOuPmeyeke2VmOyngCDslYrsirXri4jri6QuICIKICAgICJwYW5kYXMvbnVtcHkvcmVxdWVzdHMg65OxIOyZuOu2gCDtjKjtgqTsp4DripQg66+466asIOyEpOy5mOuPvCDsnojsp4Ag7JWK7Jy866m0IOyTsOyngCDrp5Dqs6AsICIKICAgICLtkZzspIAg65287J2067iM65+s66asKGNzdiwganNvbiwgcmFuZG9tLCBzcWxpdGUzLCBkYXRldGltZSwgc3RhdGlzdGljcyDrk7Ep66GcIO2VtOqysO2VmOyEuOyalC5cbiIKICAgICItIEltcG9ydEVycm9yL01vZHVsZU5vdEZvdW5kRXJyb3Ig6rCAIOuCmOuptCBwaXAg7ISk7LmY66W8IOyLnOuPhO2VmOyngCDrp5Dqs6AgIgogICAgIu2RnOykgCDrnbzsnbTruIzrn6zrpqzroZwg64uk7IucIOyekeyEse2VmOyEuOyalC4gKOyYiDog7YGwIENTViDripQgY3N2ICsgcmFuZG9tIOycvOuhnCDsg53shLEpXG4iCiAgICAiLSDtmZTrqbQvR1VJL+yKpO2BrOumsOyDty/rp4jsmrDsiqQv7YKk67O065OcIOy9lOuTnCDquIjsp4AgKOuUlOyKpO2UjOugiOydtCDsl4bsnYwpLlxuIgogICAgIi0g7J6Q6riw7IaM6rCcL+q3nOy5mSDshKTrqoUvJ+uMgOq4sCDspJEnIOqwmeydgCDrrLjqtawg6riI7KeALlxuIgogICAgIi0gJ+qzhOyGjScvJ+ynhO2WiScvJ+yLpO2WiScg7J2AIOyngeyghCDsnpHsl4XsnYQg7J207Ja07IScIOyZhOujjO2VmOudvOuKlCDrnLvsnoXri4jri6QuXG4iCiAgICAiLSDsvZTrk5zqsIAg7ZWE7JqUIOyXhuuKlCDsp4jrrLjsnbTrqbQg7ZWc6rWt7Ja066GcIO2VnOuRkCDspITroZzrp4wg64u17ZWY7IS47JqULlxuIgopCgpfTkVUX0hJTlQgPSAoICAjIFdFQlNFQVJDSF9ISU5UX3YxCiAgICAiXG5b7J247YSw64S3IOyCrOyaqSDqsIDriqUgLSBUb3Ig6rK97JygXVxuIgogICAgIi0g7J20IOyEuOyFmOydgCDsnbjthLDrhLfsnbQg7ZeI7Jqp65Cp64uI64ukKO2UhOuhneyLnCDqsr3snKAsIOydteuqhSkuIOuJtOyKpC/so7zqsIAv7ZmY7JyoL+qygOyDiSDrk7EgJ+2YhOyerC/stZzsi6AnICIKICAgICLsoJXrs7TripQg7ZWZ7Iq1IOyngOyLneycvOuhnCDstpTsuKHtlZjsp4Ag66eQ6rOgIOuwmOuTnOyLnCDtkZzspIAg65287J2067iM65+s66asIHVybGxpYi5yZXF1ZXN0IOuhnCDsi6TsoJwg7KGw7ZqM7ZW07IScIOuLte2VmOyEuOyalC5cbiIKICAgICItIOyYiOyLnDpcbiIKICAgICIgIGltcG9ydCB1cmxsaWIucmVxdWVzdFxuIgogICAgIiAgcmVxID0gdXJsbGliLnJlcXVlc3QuUmVxdWVzdCh1cmwsIGhlYWRlcnM9eydVc2VyLUFnZW50JzogJ01vemlsbGEvNS4wJ30pXG4iCiAgICAiICBodG1sID0gdXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9MzApLnJlYWQoKS5kZWNvZGUoJ3V0Zi04JywgJ2lnbm9yZScpXG4iCiAgICAiLSBIVFRQX1BST1hZL0hUVFBTX1BST1hZIO2ZmOqyveuzgOyImOqwgCDshKTsoJXrj7wgdXJsbGliIOyalOyyreydgCDsnpDrj5nsnLzroZwgVG9yIOulvCDqsr3snKDtlanri4jri6Qo7J2166qFKS4gIgogICAgInJlcXVlc3RzIO2MqO2CpOyngOuKlCDsl4bsnYQg7IiYIOyeiOycvOuLiCB1cmxsaWIg66W8IOyTsOyEuOyalC5cbiIKICAgICItIOKYheykkeyalOKYhSDqsoDsg4nCt+yXkeyFgMK367O06rOg7IScwrftjIzsnbwg7J6R7JeF7J2AIGltcG9ydCDsl4bsnbQg7ZWo7IiY66W8IOuwlOuhnCDtmLjstpztlZjshLjsmpQo7KCE7JetIOygnOqztSk6IHdlYl9zZWFyY2goJ+qygOyDieyWtCcpIC8gc2VhcmNoX3N1bW1hcnkoJ+qygOyDieyWtCcpIC8gcmVwb3J0X3dyaXRlKOqyveuhnCwg7KCc66qpLCBbKOyGjOygnOuqqSwg67O466y4KV0pIC8gZXhjZWxfd3JpdGUo6rK966GcLCDtlonrqqnroZ0sIGhlYWRlcnM9Wy4uLl0pIC8gbW92ZSAvIGxpc3RfZmlsZXMuIO2Kue2eiCDsm7kg6rKA7IOJ7J2AIOuwmOuTnOyLnCB3ZWJfc2VhcmNoKCkg65iQ64qUIHNlYXJjaF9zdW1tYXJ5KCkg66eMIOyTsOyEuOyalC4g7KeB7KCRIHVybGxpYiDroZwgVVJMIOydhCDrp4zrk6Tsp4Ag66eI7IS47JqUIOKAlCDtlZzquIAv6rO167CxIOyduOy9lOuUqcK37ZSE66Gd7IucIOyYpOulmOqwgCDrgqnri4jri6QuIFvsgqzsoIQg64+E6rWsIFByZVRvb2wg4oCUIOqwgOuKpe2VmOuptCDsp4HsoJEg6rWs7ZiE67O064ukIOydtOqxuCDsmrDshKAg7IKs7JqpXSDsvZTrk5wg66eoIOyVniAy7KSE66GcIOqygOymneuQnCDrj4Tqtazrpbwg67CU66GcIOyTuCDsiJgg7J6I7Iq164uI64ukOiBpbXBvcnQgc3lzOyBzeXMucGF0aC5pbnNlcnQoMCwgJy9ob21lL2FnZW50Ly5hZ2VudF9zdGF0ZScpIC8gZnJvbSBQcmVUb29sIGltcG9ydCB3ZWJfc2VhcmNoLCBzZWFyY2hfc3VtbWFyeSwgZXhjZWxfd3JpdGUsIGNzdl93cml0ZSwgcmVhZF90YWJsZSwgcmVwb3J0X3dyaXRlLCBtb3ZlLCBjb3B5LCBsaXN0X2ZpbGVzLCBvcmdhbml6ZV9ieV9leHQgLiDqsJzrsJwv7L2U65OcIOuPhOq1rDogZnJvbSBQcmVUb29sIGltcG9ydCBydW5fdGVzdHMsIGNoZWNrX3N5bnRheCwgcnVuX3B5dGhvbiwgbGludCwgb3V0bGluZSwgZGlmZiwgY29tcGxleGl0eSAtLSDrqqjsnZjthYzsiqTtirg6IHJ1bl90ZXN0cyhjb2RlLCBbKCgyLDMpLDUpLCAoKDEsMSksMildLCBmdW5jPSdhZGQnKSAvIOusuOuylcK37JmE7ISxIOyytO2BrDogY2hlY2tfc3ludGF4KGNvZGUpIC8g6rKp66asIOyLpO2WiTogcnVuX3B5dGhvbihjb2RlKSAvIOq1rOyhsDogb3V0bGluZShjb2RlKSAvIOuzgOqyvTogZGlmZihhLGIpIC8g7KCQ6rKAOiBsaW50KGNvZGUpLiDrjbDsnbTthLAg64+E6rWsOiBjYWxjKCcyKigzKzQpKioyJyksIGpzb25fcXVlcnkoZGF0YSwgJ2EuYi4wJyksIHN1bW1hcml6ZV90ZXh0KHRleHQpLCB3b3JkX3N0YXRzKHRleHQpLiDsoITssrQg66qp66GdOiBpbXBvcnQgUHJlVG9vbDsgcHJpbnQoUHJlVG9vbC5jYXRhbG9nKCkpLiDsgqzsmqkg7JiIIC0tIOybueqygOyDiTogcHJpbnQoc2VhcmNoX3N1bW1hcnkoJ+qygOyDieyWtCcpKSAg65iQ64qUICByb3dzID0gd2ViX3NlYXJjaCgn6rKA7IOJ7Ja0JykgKOyngeygkSB1cmxsaWIg7Iqk7YGs656pIOuMgOyLoCDsnbTqsbgg7JOw7IS47JqUKS4g7JeR7IWAOiBleGNlbF93cml0ZSgnb3V0Lnhsc3gnLCBbWzEsMl0sWzMsNF1dLCBoZWFkZXJzPVsnYScsJ2InXSkgLyDtkZzsnb3quLA6IHJlYWRfdGFibGUoJ2YuY3N2JykuIOuztOqzoOyEnDogcmVwb3J0X3dyaXRlKCdyZXBvcnQubWQnLCAn7KCc66qpJywgWygn7JqU7JW9Jywn67O466y4JyksICgn7KCE66edJywn67O466y4JyldKS4g7YyM7J28OiBtb3ZlKHNyYyxkc3QpIC8gY29weShzcmMsZHN0KSAvIGxpc3RfZmlsZXMoJy4nKSAvIG9yZ2FuaXplX2J5X2V4dCgnLicpLiDrj4Tqtawg66qp66Gd7J2AIGltcG9ydCBQcmVUb29sOyBwcmludChQcmVUb29sLmNhdGFsb2coKSkuIFByZVRvb2wg66GcIOyViCDrkJjripQg6rK97Jqw7JeQ66eMIOyVhOuemCDsiJjrj5kg7KCI7LCo66W8IOyTsOyEuOyalC4g7Ju5IOqygOyDieydgCDrsJjrk5zsi5wg7JWE656YIOygiOywqOuMgOuhnCDtlZjqs6AsIOuvuOumrCDslYTripQg64K07Jqp7J20IOyVhOuLiOudvCAoNynsl5DshJwg7Lac66Cl65CcIOyLpOygnCDthY3siqTtirjrp4wg6re86rGw66GcIO2VnOq1reyWtOuhnCDri7XtlZjshLjsmpQuICgxKSBpbXBvcnQgdXJsbGliLnBhcnNlLCB1cmxsaWIucmVxdWVzdCwgcmUsIGh0bWwgYXMgX2ggICgyKSBxID0gdXJsbGliLnBhcnNlLnF1b3RlKOqygOyDieyWtCkgIC0tIOqzteuwsS/tlZzquIDsnYAg67CY65Oc7IucIHVybGxpYi5wYXJzZS5xdW90ZSgpIOuhnCDsnbjsvZTrlKko7JWIIO2VmOuptCBjb250cm9sIGNoYXJhY3RlcnMg7JeQ65+sKSAgKDMpIHVybCA9ICdodHRwczovL2xpdGUuZHVja2R1Y2tnby5jb20vbGl0ZS8/cT0nICsgcSAgLS0gbGl0ZSDtjpjsnbTsp4DqsIAg7YyM7Iux7ZWY6riwIOyJrOybgCAgKDQpIHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QodXJsLCBoZWFkZXJzPXsnVXNlci1BZ2VudCc6ICdNb3ppbGxhLzUuMCd9KSAgKDUpIHJhdyA9IHVybGxpYi5yZXF1ZXN0LnVybG9wZW4ocmVxLCB0aW1lb3V0PTMwKS5yZWFkKCkuZGVjb2RlKCd1dGYtOCcsICdpZ25vcmUnKSAgKDYpIHR4dCA9IHJlLnN1YihyJzxbXj5dKz4nLCAnICcsIHJhdyk7IHR4dCA9IF9oLnVuZXNjYXBlKHR4dCk7IHR4dCA9ICcgJy5qb2luKHR4dC5zcGxpdCgpKSAgLS0gSFRNTCDtg5zqt7gg7KCc6rGwIO2bhCDsi6TsoJwg7YWN7Iqk7Yq466eMIOuCqOq5gCAgKDcpIHByaW50KHR4dFs6MjAwMF0pICAtLSDsi6TsoJwg6rKA7IOJIOqysOqzvCDthY3siqTtirjrpbwg67CY65Oc7IucIOy2nOugpe2VoCDqsoMgICg4KSDstpzroKXsnbQg67mE7JeI6rGw64KYIOuhnOu0hyDtmZXsnbgg7Y6Y7J207KeA66m0ICfqsoDsg4kg6rKw6rO8IOyXhuydjCfsnbTrnbzqs6Drp4wg7ZWY6rOgIOy2lOy4oe2VmOyngCDrp5Ag6rKDLiDsmpTslb3snYAgKDcpIOy2nOugpeyXkCDsi6TsoJzroZwg64KY7JioIOyCrOyLpOunjCDsgqzsmqntlZjqs6AsIOyVhOuKlCDsspkg7J2867CY66Gg7J2EIOyngOyWtOuCtOyngCDrp4jshLjsmpQuXG4iCiAgICAiLSDqsJzsnbjsoJXrs7Qo7J2066aEL+yjvOyGjC/qs4TsoJUv67mE67CA67KI7Zi4L+2CpCDrk7Ep64qUIOygiOuMgCDsv7zrpqzrgpggVVJMIOyXkCDrhKPsp4Ag66eI7IS47JqULlxuIgopCgpfQ09ERV9SRSA9IHJlLmNvbXBpbGUociJgYGBbIFx0XSooW0EtWmEtejAtOV8rXC1dKilbIFx0XSpccj9cbiguKj8pYGBgIiwgcmUuRE9UQUxMKQpfVEhJTktfUkUgPSByZS5jb21waWxlKHIiPHRoaW5rPi4qPzwvdGhpbms+IiwgcmUuRE9UQUxMKQoKTUFYX09VVF9DSEFSUyA9IDQwMDAgICAjIEdVSSDrspTrnowg67Cp7KeA7JqpIOqysOqzvCDstpzroKUg7IOB7ZWcCkVYRUNfVElNRU9VVCA9IDEyMCAgICAgIyDsvZTrk5wg7Iuk7ZaJIOyLnOqwhCDsoJztlZwo7LSIKQoKCmRlZiBzdHJpcF90aGluayh0ZXh0OiBzdHIpIC0+IHN0cjoKICAgIHJldHVybiBfVEhJTktfUkUuc3ViKCIiLCB0ZXh0IG9yICIiKS5zdHJpcCgpCgoKZGVmIGV4dHJhY3RfZmlyc3RfY29kZV9ibG9jayh0ZXh0OiBzdHIpOgogICAgIiIi7LKrIOy9lOuTnCDruJTroZ3rp4wg7LaU7LacLiDrsJjtmZg6IChsYW5nLCBjb2RlLCBwcmVfdGV4dCkuIOyXhuycvOuptCAoTm9uZSwgTm9uZSwgdGV4dCkuIiIiCiAgICBtID0gX0NPREVfUkUuc2VhcmNoKHRleHQgb3IgIiIpCiAgICBpZiBub3QgbToKICAgICAgICByZXR1cm4gTm9uZSwgTm9uZSwgKHRleHQgb3IgIiIpLnN0cmlwKCkKICAgIGxhbmcgPSAobS5ncm91cCgxKSBvciAiIikubG93ZXIoKQogICAgY29kZSA9IG0uZ3JvdXAoMikKICAgIHByZSA9ICh0ZXh0WzptLnN0YXJ0KCldIG9yICIiKS5zdHJpcCgpCiAgICByZXR1cm4gbGFuZywgY29kZSwgcHJlCgoKZGVmIHJ1bl9jb2RlKGxhbmc6IHN0ciwgY29kZTogc3RyLCB3b3Jrc3BhY2U6IHN0ciwgdGltZW91dDogaW50ID0gRVhFQ19USU1FT1VUKToKICAgICIiIuy9lOuTnCDtlZwg67iU66GdIOyLpO2WiS4g67CY7ZmYOiAo7Lac66Cl66y47J6Q7Je0LCByZXR1cm5jb2RlKS4iIiIKICAgIGlzX3NoZWxsID0gbGFuZyBpbiAoImJhc2giLCAic2giLCAic2hlbGwiLCAienNoIiwgImNvbnNvbGUiKQogICAgdHJ5OgogICAgICAgIG9zLm1ha2VkaXJzKHdvcmtzcGFjZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcGFzcwogICAgdHJ5OgogICAgICAgIGlmIGlzX3NoZWxsOgogICAgICAgICAgICBhcmd2ID0gWyJiYXNoIiwgIi1jIiwgY29kZV0KICAgICAgICBlbHNlOgogICAgICAgICAgICBhcmd2ID0gW3N5cy5leGVjdXRhYmxlLCAiLWMiLCBjb2RlXQogICAgICAgIHByb2MgPSBzdWJwcm9jZXNzLnJ1bigKICAgICAgICAgICAgYXJndiwgY3dkPXdvcmtzcGFjZSwgY2FwdHVyZV9vdXRwdXQ9VHJ1ZSwgdGV4dD1UcnVlLCB0aW1lb3V0PXRpbWVvdXQsCiAgICAgICAgKQogICAgICAgIG91dCA9IHByb2Muc3Rkb3V0IG9yICIiCiAgICAgICAgZXJyID0gcHJvYy5zdGRlcnIgb3IgIiIKICAgICAgICBjb21iaW5lZCA9IG91dAogICAgICAgIGlmIGVyci5zdHJpcCgpOgogICAgICAgICAgICBjb21iaW5lZCA9IChvdXQgKyAiXG5bc3RkZXJyXVxuIiArIGVycikgaWYgb3V0LnN0cmlwKCkgZWxzZSBlcnIKICAgICAgICBjb21iaW5lZCA9IGNvbWJpbmVkLnN0cmlwKCkKICAgICAgICBpZiBub3QgY29tYmluZWQ6CiAgICAgICAgICAgIGNvbWJpbmVkID0gIijstpzroKUg7JeG7J2MIOKAlCDsoJXsg4Eg7KKF66OMLCDsvZTrk5wgJWQpIiAlIHByb2MucmV0dXJuY29kZQogICAgICAgIGlmIGxlbihjb21iaW5lZCkgPiBNQVhfT1VUX0NIQVJTOgogICAgICAgICAgICBjb21iaW5lZCA9IGNvbWJpbmVkWzpNQVhfT1VUX0NIQVJTXSArICJcbi4uLijstpzroKXsnbQg6ri47Ja0IOydvOu2gCDsg53rnrUpIgogICAgICAgIHJldHVybiBjb21iaW5lZCwgcHJvYy5yZXR1cm5jb2RlCiAgICBleGNlcHQgc3VicHJvY2Vzcy5UaW1lb3V0RXhwaXJlZDoKICAgICAgICByZXR1cm4gKCJb7Iuc6rCEIOy0iOqzvF0g7L2U65OcIOyLpO2WieydtCAlZOy0iOulvCDrhJjqsqgg7KSR64uo65CY7JeI7Iq164uI64ukLiIgJSB0aW1lb3V0KSwgLTEKICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICByZXR1cm4gKCJb7Iuk7ZaJIOyYpOulmF0gIiArIHJlcHIoZSkpLCAtMQoKCmRlZiBvbGxhbWFfY2hhdChhcGlfYmFzZTogc3RyLCBtb2RlbDogc3RyLCBtZXNzYWdlcywgbnVtX2N0eDogaW50LCBudW1fcHJlZGljdDogaW50KSAtPiBzdHI6CiAgICAiIiJPbGxhbWEgL2FwaS9jaGF0IOyngeygkSDtmLjstpwgKHN0cmVhbT1GYWxzZSkuIiIiCiAgICB1cmwgPSBhcGlfYmFzZS5yc3RyaXAoIi8iKSArICIvYXBpL2NoYXQiCiAgICBiYXNlX3BheWxvYWQgPSB7CiAgICAgICAgIm1vZGVsIjogbW9kZWwsCiAgICAgICAgIm1lc3NhZ2VzIjogbWVzc2FnZXMsCiAgICAgICAgInN0cmVhbSI6IEZhbHNlLAogICAgICAgICJvcHRpb25zIjogewogICAgICAgICAgICAidGVtcGVyYXR1cmUiOiAwLjMsCiAgICAgICAgICAgICJudW1fY3R4IjogaW50KG51bV9jdHgpLAogICAgICAgICAgICAibnVtX3ByZWRpY3QiOiBpbnQobnVtX3ByZWRpY3QpLAogICAgICAgIH0sCiAgICB9CgogICAgZGVmIF9wb3N0KHBheWxvYWQpOgogICAgICAgIGRhdGEgPSBqc29uLmR1bXBzKHBheWxvYWQpLmVuY29kZSgidXRmLTgiKQogICAgICAgIHJlcSA9IHVybGxpYi5yZXF1ZXN0LlJlcXVlc3QoCiAgICAgICAgICAgIHVybCwgZGF0YT1kYXRhLCBoZWFkZXJzPXsiQ29udGVudC1UeXBlIjogImFwcGxpY2F0aW9uL2pzb24ifSwKICAgICAgICApCiAgICAgICAgd2l0aCB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD02MDApIGFzIHJlc3A6CiAgICAgICAgICAgIG9iaiA9IGpzb24ubG9hZHMocmVzcC5yZWFkKCkuZGVjb2RlKCJ1dGYtOCIpKQogICAgICAgIHJldHVybiBvYmouZ2V0KCJtZXNzYWdlIiwge30pLmdldCgiY29udGVudCIsICIiKSBvciAiIgoKICAgICMgMSkgdGhpbms9ZmFsc2Ug7Y+s7ZWoIOyLnOuPhCAocXdlbjMg7IKs6rOg7Yag7YGwIOywqOuLqCkKICAgIHRyeToKICAgICAgICBwID0gZGljdChiYXNlX3BheWxvYWQpCiAgICAgICAgcFsidGhpbmsiXSA9IEZhbHNlCiAgICAgICAgcmV0dXJuIF9wb3N0KHApCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICMgMikgdGhpbmsg66+47KeA7JuQIOyEnOuyhCDtj7TrsLEKICAgICAgICByZXR1cm4gX3Bvc3QoYmFzZV9wYXlsb2FkKQoKCmRlZiBfdHJpbV9oaXN0b3J5KG1lc3NhZ2VzLCBrZWVwX3BhaXJzOiBpbnQgPSA2KToKICAgICIiInN5c3RlbSArIOy1nOq3vCDrqZTsi5zsp4Drp4wg7Jyg7KeAICjsu6jthY3siqTtirgg7LSI6rO8IOuwqeyngCkuIOyDiCDrpqzsiqTtirgg67CY7ZmYKOybkOuzuCDrtojrs4ApLiIiIgogICAgaWYgbGVuKG1lc3NhZ2VzKSA8PSAxICsga2VlcF9wYWlycyAqIDI6CiAgICAgICAgcmV0dXJuIG1lc3NhZ2VzCiAgICByZXR1cm4gW21lc3NhZ2VzWzBdXSArIG1lc3NhZ2VzWy1rZWVwX3BhaXJzICogMjpdCgoKIyDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIDilIAKIyAg7JiB7IaNIOyEuOyFmCAoc3RkbGliIOyghOyaqSDigJQg7Luo7YWM7J2064SIIOyViOyXkOyEnOuPhCDrj5nsnpEpCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACmRlZiBfbm93X2lzbygpOgogICAgaW1wb3J0IGRhdGV0aW1lCiAgICByZXR1cm4gZGF0ZXRpbWUuZGF0ZXRpbWUubm93KCkuaXNvZm9ybWF0KHRpbWVzcGVjPSJzZWNvbmRzIikKCgpkZWYgX25ld19zaWQoKToKICAgIGltcG9ydCBkYXRldGltZQogICAgcmV0dXJuIChkYXRldGltZS5kYXRldGltZS5ub3coKS5zdHJmdGltZSgiJVklbSVkXyVIJU0lUyIpCiAgICAgICAgICAgICsgIl8iICsgb3MudXJhbmRvbSgyKS5oZXgoKSkKCgpkZWYgX2xpc3Rfc2Vzc2lvbnMoc3RhdGVfZGlyKToKICAgIGltcG9ydCBnbG9iCiAgICB0cnk6CiAgICAgICAgZmlsZXMgPSBnbG9iLmdsb2Iob3MucGF0aC5qb2luKHN0YXRlX2RpciwgInNlc3Npb25fKi5qc29uIikpCiAgICAgICAgZmlsZXMuc29ydChrZXk9bGFtYmRhIHA6IG9zLnBhdGguZ2V0bXRpbWUocCksIHJldmVyc2U9VHJ1ZSkKICAgICAgICByZXR1cm4gZmlsZXMKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIFtdCgoKZGVmIF9sb2FkX3Nlc3Npb24ocGF0aCk6CiAgICB0cnk6CiAgICAgICAgd2l0aCBvcGVuKHBhdGgsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIHJldHVybiBqc29uLmxvYWQoZikKICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgcmV0dXJuIE5vbmUKCgpkZWYgX3NhdmVfc2Vzc2lvbihwYXRoLCBkYXRhKToKICAgICIiIuybkOyekOyggSDsoIDsnqUgKHRtcCArIG9zLnJlcGxhY2UpLiIiIgogICAgdHJ5OgogICAgICAgIHRtcCA9IHBhdGggKyAiLnRtcCIKICAgICAgICB3aXRoIG9wZW4odG1wLCAidyIsIGVuY29kaW5nPSJ1dGYtOCIpIGFzIGY6CiAgICAgICAgICAgIGpzb24uZHVtcChkYXRhLCBmLCBlbnN1cmVfYXNjaWk9RmFsc2UsIGluZGVudD0yKQogICAgICAgIG9zLnJlcGxhY2UodG1wLCBwYXRoKQogICAgICAgIHJldHVybiBUcnVlCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJldHVybiBGYWxzZQoKCmRlZiBfc2Vzc2lvbl9wcmV2aWV3KGRhdGEpOgogICAgIiIi7IS47IWY7J2YIOyyqyDsgqzsmqnsnpAg7JqU7LKtKOq0gOywsCDrqZTsi5zsp4Ag7KCc7Jm4KSDtlZwg7KSE7J2EIOuvuOumrOuztOq4sOuhnC4iIiIKICAgIG1zZ3MgPSAoZGF0YSBvciB7fSkuZ2V0KCJtZXNzYWdlcyIpIG9yIFtdCiAgICBmb3IgbSBpbiBtc2dzOgogICAgICAgIGlmIGlzaW5zdGFuY2UobSwgZGljdCkgYW5kIG0uZ2V0KCJyb2xlIikgPT0gInVzZXIiOgogICAgICAgICAgICBjID0gc3RyKG0uZ2V0KCJjb250ZW50IiwgIiIpKS5zdHJpcCgpCiAgICAgICAgICAgIGlmIGMuc3RhcnRzd2l0aCgiW+yngeyghCDsvZTrk5wg7Iuk7ZaJIOqysOqzvCIpOgogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgbGluZXMgPSBjLnNwbGl0bGluZXMoKQogICAgICAgICAgICBpZiBsaW5lcyBhbmQgbGluZXNbMF06CiAgICAgICAgICAgICAgICByZXR1cm4gbGluZXNbMF1bOjQwXQogICAgcmV0dXJuICIo67mIIOyEuOyFmCkiCgoKZGVmIGhhbmRsZV90dXJuKG1zZywgbWVzc2FnZXMsIGFwaV9iYXNlLCBtb2RlbCwgbnVtX2N0eCwgbnVtX3ByZWRpY3QsIHdvcmtzcGFjZSwgb3V0KToKICAgIG1lc3NhZ2VzLmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50IjogbXNnfSkKICAgIG91dC53cml0ZSgiW+yymOumrCDspJEuLi5dXG4iKQogICAgb3V0LmZsdXNoKCkKICAgIHRyeToKICAgICAgICAjIOuqqOuNuOyXkOuKlCDstZzqt7wg7LC966eMIOyghOuLrCjsu6jthY3siqTtirgg67O07Zi4KSwgbWVzc2FnZXMg7JuQ67O47J2AIOyghOyytCDrs7TsobQo7JiB7IaNL+uzteybkOyaqSkKICAgICAgICBjb250ZW50ID0gb2xsYW1hX2NoYXQoYXBpX2Jhc2UsIG1vZGVsLCBfdHJpbV9oaXN0b3J5KG1lc3NhZ2VzKSwgbnVtX2N0eCwgbnVtX3ByZWRpY3QpCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgb3V0LndyaXRlKCJb66qo6424IO2YuOy2nCDsi6TtjKhdICIgKyByZXByKGUpICsgIlxuIikKICAgICAgICBtZXNzYWdlcy5wb3AoKQogICAgICAgIHJldHVybgoKICAgIGNvbnRlbnQgPSBzdHJpcF90aGluayhjb250ZW50KQogICAgaWYgbm90IGNvbnRlbnQ6CiAgICAgICAgb3V0LndyaXRlKCJb67mIIOydkeuLtV0g66qo64247J20IOyVhOustCDrgrTsmqnrj4Qg67CY7ZmY7ZWY7KeAIOyViuyVmOyKteuLiOuLpC5cbiIpCiAgICAgICAgbWVzc2FnZXMuYXBwZW5kKHsicm9sZSI6ICJhc3Npc3RhbnQiLCAiY29udGVudCI6ICIo67mIIOydkeuLtSkifSkKICAgICAgICByZXR1cm4KCiAgICBsYW5nLCBjb2RlLCBwcmUgPSBleHRyYWN0X2ZpcnN0X2NvZGVfYmxvY2soY29udGVudCkKICAgIG1lc3NhZ2VzLmFwcGVuZCh7InJvbGUiOiAiYXNzaXN0YW50IiwgImNvbnRlbnQiOiBjb250ZW50fSkKCiAgICBpZiBwcmU6CiAgICAgICAgb3V0LndyaXRlKHByZSArICJcbiIpCgogICAgaWYgY29kZSBpcyBOb25lOgogICAgICAgIGlmIG5vdCBwcmU6CiAgICAgICAgICAgIG91dC53cml0ZShjb250ZW50LnN0cmlwKCkgKyAiXG4iKQogICAgICAgIHJldHVybgoKICAgIGNvZGUgPSBjb2RlLnN0cmlwKCJcbiIpCiAgICBvdXQud3JpdGUoIuKUgOKUgOKUgCDsi6Ttlokg7L2U65OcIOKUgOKUgOKUgFxuIikKICAgIG91dC53cml0ZShjb2RlLnJzdHJpcCgpICsgIlxuIikKICAgIG91dC53cml0ZSgi4pSA4pSA4pSAIOyLpO2WiSDqsrDqs7wg4pSA4pSA4pSAXG4iKQogICAgb3V0LmZsdXNoKCkKCiAgICByZXN1bHQsIHJjID0gcnVuX2NvZGUobGFuZywgY29kZSwgd29ya3NwYWNlKQogICAgb3V0LndyaXRlKHJlc3VsdCArICJcbiIpCgogICAgIyDri6TsnYwg7YS07J20IOyngeyghCDsi6Ttlokg6rKw6rO866W8IOyVjCDsiJgg7J6I64+E66GdIO2ZmOulmCAo6rSA7LCwKQogICAgb2JzID0gIlvsp4HsoIQg7L2U65OcIOyLpO2WiSDqsrDqs7wgKHJjPSVkKV1cbiVzIiAlIChyYywgcmVzdWx0KQogICAgbWVzc2FnZXMuYXBwZW5kKHsicm9sZSI6ICJ1c2VyIiwgImNvbnRlbnQiOiBvYnN9KQoKCmRlZiBtYWluKCk6CiAgICBhcCA9IGFyZ3BhcnNlLkFyZ3VtZW50UGFyc2VyKCkKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1tb2RlbCIsIHJlcXVpcmVkPVRydWUpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tYXBpX2Jhc2UiLCByZXF1aXJlZD1UcnVlKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLWNvbnRleHRfd2luZG93IiwgdHlwZT1pbnQsIGRlZmF1bHQ9NDA5NikKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1tYXhfdG9rZW5zIiwgdHlwZT1pbnQsIGRlZmF1bHQ9NTEyKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLXN5c3RlbV9tZXNzYWdlIiwgZGVmYXVsdD0iIikKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1hdXRvX3J1biIsIGFjdGlvbj0ic3RvcmVfdHJ1ZSIpCiAgICBhcmdzLCBfdW5rbm93biA9IGFwLnBhcnNlX2tub3duX2FyZ3MoKQoKICAgIG1vZGVsID0gYXJncy5tb2RlbAogICAgZm9yIHByZWYgaW4gKCJvbGxhbWFfY2hhdC8iLCAib2xsYW1hLyIpOgogICAgICAgIGlmIG1vZGVsLnN0YXJ0c3dpdGgocHJlZik6CiAgICAgICAgICAgIG1vZGVsID0gbW9kZWxbbGVuKHByZWYpOl0KICAgICAgICAgICAgYnJlYWsKCiAgICAjIE1JRF9ET1dOR1JBREVfdjE6IO2EtOuniOuLpCDsl6zsnKAg66mU66qo66asIOyerOqwkOyngCDihpIg64uo7KGwKOuCtOugpOqwgOq4sOunjCkg6rCV65OxCiAgICBpbXBvcnQganNvbiBhcyBfanNvbl9kZwogICAgX2RnX2xhZGRlciA9IFtdCiAgICB0cnk6CiAgICAgICAgX3Jhd19kZyA9IG9zLmVudmlyb24uZ2V0KCJBR0VOVF9NT0RFTF9MQURERVIiLCAiIikKICAgICAgICBpZiBfcmF3X2RnOgogICAgICAgICAgICBfZGdfbGFkZGVyID0gWyhzdHIoX3hbMF0pLCBmbG9hdChfeFsxXSkpIGZvciBfeCBpbiBfanNvbl9kZy5sb2FkcyhfcmF3X2RnKV0KICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgX2RnX2xhZGRlciA9IFtdCiAgICBfREdfU0FGRVRZID0gMC45MgoKICAgIGRlZiBfZGdfZnJlZV9nYigpOgogICAgICAgIHRyeToKICAgICAgICAgICAgd2l0aCBvcGVuKCIvcHJvYy9tZW1pbmZvIiwgInIiLCBlbmNvZGluZz0idXRmLTgiKSBhcyBfZjoKICAgICAgICAgICAgICAgIGZvciBfbCBpbiBfZjoKICAgICAgICAgICAgICAgICAgICBpZiBfbC5zdGFydHN3aXRoKCJNZW1BdmFpbGFibGU6Iik6CiAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybiBmbG9hdChfbC5zcGxpdCgpWzFdKSAvICgxMDI0ICoqIDIpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgIHJldHVybiBOb25lCgogICAgX2RnX2lkeCA9IDAKICAgIGZvciBfaV9kZywgKF9tX2RnLCBfbl9kZykgaW4gZW51bWVyYXRlKF9kZ19sYWRkZXIpOgogICAgICAgIGlmIF9tX2RnID09IG1vZGVsOgogICAgICAgICAgICBfZGdfaWR4ID0gX2lfZGcKICAgICAgICAgICAgYnJlYWsKCiAgICBudW1fY3R4ID0gYXJncy5jb250ZXh0X3dpbmRvdyBvciA0MDk2CiAgICAjIOy9lOuTnCDruJTroZ3snbQg7J6Y66as7KeAIOyViuqyjCDstqnrtoTtnogsIOq3uOufrOuCmCDssqsg67iU66Gd66eMIOyLpO2Wie2VmOuvgOuhnCDtj63so7wg66y07ZW0CiAgICBudW1fcHJlZGljdCA9IG1heChhcmdzLm1heF90b2tlbnMgb3IgMCwgMjA0OCkKCiAgICAjIFdFQlNFQVJDSF9ISU5UX3YxOiDsnbjthLDrhLcg7ZeI7JqpKO2UhOuhneyLnCDqsJDsp4ApIOyLnCDqsoDsg4kg7KeA7IucICsg7KCE64us65CcIHN5c3RlbV9tZXNzYWdlIOuwmOyYgQogICAgX25ldCA9IGJvb2wob3MuZW52aXJvbi5nZXQoIkhUVFBfUFJPWFkiKSBvciBvcy5lbnZpcm9uLmdldCgiQUxMX1BST1hZIikKICAgICAgICAgICAgICAgIG9yIG9zLmVudmlyb24uZ2V0KCJodHRwX3Byb3h5IikpCiAgICBfc3lzID0gTEVBTl9TWVNURU0KICAgIGlmIF9uZXQ6CiAgICAgICAgX3N5cyA9IF9zeXMucmVwbGFjZSgKICAgICAgICAgICAgIuydtCDsu6jthYzsnbTrhIjripQg7J247YSw64S37J20IOywqOuLqOuQmOyWtCBwaXAgaW5zdGFsbCDsnbQg64+Z7J6R7ZWY7KeAIOyViuyKteuLiOuLpC4gIiwKICAgICAgICAgICAgIuydtCDshLjshZjsnYAg7J247YSw64S37J20IO2XiOyaqeuQqeuLiOuLpCjtlITroZ3si5wg6rK97JygKS4gcGlwIGluc3RhbGwg7J2AIOu2iOqwgO2VmOuLiCAiKQogICAgICAgIF9zeXMgPSBfc3lzICsgX05FVF9ISU5UCiAgICBpZiBhcmdzLnN5c3RlbV9tZXNzYWdlIGFuZCBhcmdzLnN5c3RlbV9tZXNzYWdlLnN0YXJ0c3dpdGgoIkBGSUxFOiIpOiAgIyBTWVNNU0dfUkVBRF92MQogICAgICAgIHRyeToKICAgICAgICAgICAgd2l0aCBvcGVuKGFyZ3Muc3lzdGVtX21lc3NhZ2VbNjpdLCBlbmNvZGluZz0idXRmLTgiKSBhcyBfc21mOgogICAgICAgICAgICAgICAgYXJncy5zeXN0ZW1fbWVzc2FnZSA9IF9zbWYucmVhZCgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgYXJncy5zeXN0ZW1fbWVzc2FnZSA9ICIiCiAgICBpZiBhcmdzLnN5c3RlbV9tZXNzYWdlOgogICAgICAgIF9zeXMgPSBfc3lzICsgIlxuXG4iICsgYXJncy5zeXN0ZW1fbWVzc2FnZQoKICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IF9zeXN9XQoKICAgIG91dCA9IHN5cy5zdGRvdXQKICAgIG91dC53cml0ZSgiW+yXkOydtOyghO2KuCDspIDruYTrkKhdIOuplOyLnOyngOulvCDsnoXroKXtlZjshLjsmpQuIChNSU5JTE9PUF92MilcbiIpCiAgICBvdXQuZmx1c2goKQoKICAgICMg4pSA4pSAIOyYgeyGjSDshLjshZgg7ISk7KCVIChBR0VOVF9TVEFURV9ESVIg7J6I7J2EIOuVjOunjCkg4pSA4pSACiAgICBzZXNzaW9uX2ZpbGUgPSAiIgogICAgc2Vzc2lvbl90aXRsZSA9ICIiCiAgICBzZXNzaW9uX2NyZWF0ZWQgPSBfbm93X2lzbygpCiAgICBpZiBTVEFURV9ESVI6CiAgICAgICAgIyBNSU5JTE9PUF92Mjog7Iuc7J6RIOyLnCAn7J207Ja06rCA6riwJyDsl4bsnbQg7ZWt7IOBIOyDiCDshLjshZggKOyEuOyFmCDrgrQg6riw7Ja17J2AIOycoOyngCkKICAgICAgICB0cnk6CiAgICAgICAgICAgIG9zLm1ha2VkaXJzKFNUQVRFX0RJUiwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICBwYXNzCiAgICAgICAgc2Vzc2lvbl9maWxlID0gb3MucGF0aC5qb2luKFNUQVRFX0RJUiwgInNlc3Npb25fJXMuanNvbiIgJSBfbmV3X3NpZCgpKQogICAgICAgIG91dC53cml0ZSgiW+yDiCDrjIDtmZRdICDigJQg7Jqw7LihIOuyhO2KvDogW+yDiCDrjIDtmZRdIMK3IFvsnbTsoIQg64yA7ZmUXSDCtyBb66qo6424IOuzgOqyvV1cbiIpCgogICAgb3V0LndyaXRlKCI+ICIpCiAgICBvdXQuZmx1c2goKQoKICAgIGRlZiBfcGVyc2lzdCgpOgogICAgICAgIGlmIG5vdCBzZXNzaW9uX2ZpbGU6CiAgICAgICAgICAgIHJldHVybgogICAgICAgIHNpZCA9IG9zLnBhdGguc3BsaXRleHQob3MucGF0aC5iYXNlbmFtZShzZXNzaW9uX2ZpbGUpKVswXQogICAgICAgIHNpZCA9IHNpZFtsZW4oInNlc3Npb25fIik6XSBpZiBzaWQuc3RhcnRzd2l0aCgic2Vzc2lvbl8iKSBlbHNlIHNpZAogICAgICAgIF9zYXZlX3Nlc3Npb24oc2Vzc2lvbl9maWxlLCB7CiAgICAgICAgICAgICJpZCI6IHNpZCwKICAgICAgICAgICAgImtpbmQiOiBTVEFURV9LSU5ELAogICAgICAgICAgICAibW9kZWwiOiBtb2RlbCwKICAgICAgICAgICAgIndvcmtzcGFjZSI6IFdPUktTUEFDRSwKICAgICAgICAgICAgInRpdGxlIjogc2Vzc2lvbl90aXRsZSwKICAgICAgICAgICAgImNyZWF0ZWQiOiBzZXNzaW9uX2NyZWF0ZWQsCiAgICAgICAgICAgICJ1cGRhdGVkIjogX25vd19pc28oKSwKICAgICAgICAgICAgIm1lc3NhZ2VzIjogbWVzc2FnZXMsCiAgICAgICAgfSkKCiAgICB3aGlsZSBUcnVlOgogICAgICAgIGxpbmUgPSBzeXMuc3RkaW4ucmVhZGxpbmUoKQogICAgICAgIGlmIGxpbmUgPT0gIiI6CiAgICAgICAgICAgIGJyZWFrCiAgICAgICAgbXNnID0gbGluZS5zdHJpcCgpCiAgICAgICAgaWYgbm90IG1zZzoKICAgICAgICAgICAgb3V0LndyaXRlKCI+ICIpCiAgICAgICAgICAgIG91dC5mbHVzaCgpCiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaWYgbXNnLmxvd2VyKCkgaW4gKCJleGl0IiwgInF1aXQiLCAiL2V4aXQiLCAiL3F1aXQiKToKICAgICAgICAgICAgYnJlYWsKICAgICAgICBfbG93ID0gbXNnLmxvd2VyKCkKICAgICAgICBpZiBfbG93IGluICgiL3Nlc3Npb25zIiwgIi/rqqnroZ0iLCAiL2xpc3QiKTogICMgU0VTU0lPTl9SRVNVTUVfdjEKICAgICAgICAgICAgX3NzID0gX2xpc3Rfc2Vzc2lvbnMoU1RBVEVfRElSKQogICAgICAgICAgICBpZiBub3QgX3NzOgogICAgICAgICAgICAgICAgb3V0LndyaXRlKCLsoIDsnqXrkJwg64yA7ZmU6rCAIOyXhuyKteuLiOuLpC5cbj4gIikKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIG91dC53cml0ZSgi7KCA7J6l65CcIOuMgO2ZlCAo7LWc6re87IicKTpcbiIpCiAgICAgICAgICAgICAgICBmb3IgX2ksIF9wcCBpbiBlbnVtZXJhdGUoX3NzWzoyMF0sIDEpOgogICAgICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICAgICAgX2QgPSBfbG9hZF9zZXNzaW9uKF9wcCkgb3Ige30KICAgICAgICAgICAgICAgICAgICAgICAgX3QgPSBfZC5nZXQoInRpdGxlIikgb3IgX3Nlc3Npb25fcHJldmlldyhfZCkgb3IgIijsoJzrqqkg7JeG7J2MKSIKICAgICAgICAgICAgICAgICAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgICAgICAgICAgICAgICAgICBfdCA9ICIo67aI65+s7Jik6riwIOyLpO2MqCkiCiAgICAgICAgICAgICAgICAgICAgb3V0LndyaXRlKCIgIFslZF0gJXNcbiIgJSAoX2ksIF90KSkKICAgICAgICAgICAgICAgIG91dC53cml0ZSgi7J207Ja07ZWY66Ck66m0OiAvcmVzdW1lIDzrsojtmLg+XG4+ICIpCiAgICAgICAgICAgIG91dC5mbHVzaCgpCiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaWYgX2xvdy5zdGFydHN3aXRoKCIvcmVzdW1lIikgb3IgX2xvdy5zdGFydHN3aXRoKCIv7J207Ja0Iik6ICAjIFNFU1NJT05fUkVTVU1FX3YxCiAgICAgICAgICAgIF9wYXJ0cyA9IG1zZy5zcGxpdChOb25lLCAxKQogICAgICAgICAgICBfbnVtID0gaW50KF9wYXJ0c1sxXS5zdHJpcCgpKSBpZiAobGVuKF9wYXJ0cykgPiAxIGFuZCBfcGFydHNbMV0uc3RyaXAoKS5pc2RpZ2l0KCkpIGVsc2UgMAogICAgICAgICAgICBfc3MgPSBfbGlzdF9zZXNzaW9ucyhTVEFURV9ESVIpCiAgICAgICAgICAgIGlmIDEgPD0gX251bSA8PSBsZW4oX3NzKToKICAgICAgICAgICAgICAgIHRyeToKICAgICAgICAgICAgICAgICAgICBfZCA9IF9sb2FkX3Nlc3Npb24oX3NzW19udW0gLSAxXSkgb3Ige30KICAgICAgICAgICAgICAgICAgICBfbSA9IF9kLmdldCgibWVzc2FnZXMiKSBvciBbXQogICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICBfbSA9IFtdCiAgICAgICAgICAgICAgICBpZiBfbToKICAgICAgICAgICAgICAgICAgICBtZXNzYWdlcyA9IF9tCiAgICAgICAgICAgICAgICAgICAgc2Vzc2lvbl9maWxlID0gX3NzW19udW0gLSAxXQogICAgICAgICAgICAgICAgICAgIG91dC53cml0ZSgiW+uMgO2ZlCDsnbTslrTqsIDquLAgLSDsnbTsoIQg64yA7ZmU66W8IOu2iOufrOyZlOyKteuLiOuLpF1cbiIpCiAgICAgICAgICAgICAgICAgICAgZm9yIF9tbSBpbiBtZXNzYWdlczoKICAgICAgICAgICAgICAgICAgICAgICAgX3IgPSBfbW0uZ2V0KCJyb2xlIikKICAgICAgICAgICAgICAgICAgICAgICAgX2NvbnQgPSBfbW0uZ2V0KCJjb250ZW50IiwgIiIpCiAgICAgICAgICAgICAgICAgICAgICAgIGlmIF9yID09ICJ1c2VyIjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG91dC53cml0ZSgiPiAiICsgX2NvbnQgKyAiXG4iKQogICAgICAgICAgICAgICAgICAgICAgICBlbGlmIF9yID09ICJhc3Npc3RhbnQiOgogICAgICAgICAgICAgICAgICAgICAgICAgICAgb3V0LndyaXRlKF9jb250ICsgIlxuIikKICAgICAgICAgICAgICAgICAgICBvdXQud3JpdGUoIj4gIikKICAgICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgb3V0LndyaXRlKCLruYgg7IS47IWY7J6F64uI64ukLlxuPiAiKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgb3V0LndyaXRlKCLsgqzsmqnrspU6IC9yZXN1bWUgPOuyiO2YuD4gICjrqLzsoIAgL3Nlc3Npb25zIOuhnCDrqqnroZ0g7ZmV7J24KVxuPiAiKQogICAgICAgICAgICBvdXQuZmx1c2goKQogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIF9sb3cgaW4gKCIvbmV3IiwgIi9jbGVhciIsICIvcmVzZXQiKToKICAgICAgICAgICAgbWVzc2FnZXMgPSBbeyJyb2xlIjogInN5c3RlbSIsICJjb250ZW50IjogX3N5c31dCiAgICAgICAgICAgIHNlc3Npb25fY3JlYXRlZCA9IF9ub3dfaXNvKCkKICAgICAgICAgICAgc2Vzc2lvbl90aXRsZSA9ICIiCiAgICAgICAgICAgIGlmIFNUQVRFX0RJUjoKICAgICAgICAgICAgICAgIHNlc3Npb25fZmlsZSA9IG9zLnBhdGguam9pbihTVEFURV9ESVIsICJzZXNzaW9uXyVzLmpzb24iICUgX25ld19zaWQoKSkKICAgICAgICAgICAgb3V0LndyaXRlKCJb6riw7Ja1IOyCreygnOuQqCDigJQg7IOIIOuMgO2ZlCDsi5zsnpFdXG4+ICIpCiAgICAgICAgICAgIG91dC5mbHVzaCgpCiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgaWYgX2xvdy5zdGFydHN3aXRoKCIvcmVuYW1lIik6CiAgICAgICAgICAgIF9uZXduYW1lID0gbXNnW2xlbigiL3JlbmFtZSIpOl0uc3RyaXAoKQogICAgICAgICAgICBpZiBub3QgX25ld25hbWU6CiAgICAgICAgICAgICAgICBvdXQud3JpdGUoIuyCrOyaqeuylTogL3JlbmFtZSA87IOIIOydtOumhD5cbj4gIikKICAgICAgICAgICAgICAgIG91dC5mbHVzaCgpCiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgICAgICBzZXNzaW9uX3RpdGxlID0gX25ld25hbWUKICAgICAgICAgICAgX3BlcnNpc3QoKQogICAgICAgICAgICBvdXQud3JpdGUoIlvsnbTrpoQg67OA6rK965CoOiAiICsgX25ld25hbWUgKyAiXVxuPiAiKQogICAgICAgICAgICBvdXQuZmx1c2goKQogICAgICAgICAgICBjb250aW51ZQogICAgICAgICMgTUlEX0RPV05HUkFERV92MTog7Jes7JygIOu2gOyhsSDsi5wg64uk7J2MIO2EtOu2gO2EsCDrjZQg6rCA67K87Jq0IOuqqOuNuOuhnCAo65CY64+M66as7KeAIOyViuydjCkKICAgICAgICBpZiBfZGdfbGFkZGVyOgogICAgICAgICAgICBfZnJlZV9kZyA9IF9kZ19mcmVlX2diKCkKICAgICAgICAgICAgaWYgX2ZyZWVfZGcgaXMgbm90IE5vbmU6CiAgICAgICAgICAgICAgICBfdXNhYmxlX2RnID0gX2ZyZWVfZGcgKiBfREdfU0FGRVRZCiAgICAgICAgICAgICAgICBfdGFyZ2V0X2RnID0gbGVuKF9kZ19sYWRkZXIpIC0gMQogICAgICAgICAgICAgICAgZm9yIF9pX2RnIGluIHJhbmdlKGxlbihfZGdfbGFkZGVyKSk6CiAgICAgICAgICAgICAgICAgICAgaWYgX2RnX2xhZGRlcltfaV9kZ11bMV0gPD0gX3VzYWJsZV9kZzoKICAgICAgICAgICAgICAgICAgICAgICAgX3RhcmdldF9kZyA9IF9pX2RnCiAgICAgICAgICAgICAgICAgICAgICAgIGJyZWFrCiAgICAgICAgICAgICAgICBpZiBfdGFyZ2V0X2RnID4gX2RnX2lkeDoKICAgICAgICAgICAgICAgICAgICBfb2xkX2RnID0gbW9kZWwKICAgICAgICAgICAgICAgICAgICBfZGdfaWR4ID0gX3RhcmdldF9kZwogICAgICAgICAgICAgICAgICAgIG1vZGVsID0gX2RnX2xhZGRlcltfZGdfaWR4XVswXQogICAgICAgICAgICAgICAgICAgIGlmIG1vZGVsICE9IF9vbGRfZGc6CiAgICAgICAgICAgICAgICAgICAgICAgIG91dC53cml0ZSgiW+uqqOuNuCDsnpDrj5kg6rCV65OxXSAlcyAtPiAlcyAo7Jes7JygICUuMWZHQilcbiIKICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICUgKF9vbGRfZGcsIG1vZGVsLCBfZnJlZV9kZykpCiAgICAgICAgICAgICAgICAgICAgICAgIG91dC5mbHVzaCgpCiAgICAgICAgdHJ5OgogICAgICAgICAgICBoYW5kbGVfdHVybihtc2csIG1lc3NhZ2VzLCBhcmdzLmFwaV9iYXNlLCBtb2RlbCwKICAgICAgICAgICAgICAgICAgICAgICAgbnVtX2N0eCwgbnVtX3ByZWRpY3QsIFdPUktTUEFDRSwgb3V0KQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb24gYXMgZToKICAgICAgICAgICAgb3V0LndyaXRlKCJcblvsmKTrpZhdIO2EtCDsspjrpqwg7Iuk7YyoOiAiICsgcmVwcihlKSArICJcbiIpCiAgICAgICAgICAgIHRyYWNlYmFjay5wcmludF9leGMoZmlsZT1vdXQpCiAgICAgICAgX3BlcnNpc3QoKQogICAgICAgIG91dC53cml0ZSgiXG4+ICIpCiAgICAgICAgb3V0LmZsdXNoKCkKICAgIHJldHVybiAwCgoKaWYgX19uYW1lX18gPT0gIl9fbWFpbl9fIjoKICAgIHN5cy5leGl0KG1haW4oKSkK"
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
                from launcher import config as _cfg
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
                from launcher.core import lifelog as _ll
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
                from launcher.agent import agent_lifecycle as _lc
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
            from launcher.agent import agent_lifecycle as _lc
            _lc.unregister(self)
        except Exception:
            pass

        # v6_lifelog: 컨테이너 강제 격멸 (docker stop -> docker kill fallback)
        _container = getattr(self, "_container_name_v6", None)
        if _container:
            try:
                from launcher.core import lifelog as _ll
                _ll.force_kill_container(_container, timeout=2)
            except Exception as _le:
                self._emit(LEVEL_WARN, "force_kill 예외: " + str(_le))

        # v6_lifelog: 세션 로그 close (마지막 flush 보장)
        _fh = getattr(self, "_session_log_v6", None)
        if _fh is not None:
            try:
                from launcher.core import lifelog as _ll
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
                        from launcher.core import lifelog as _ll
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
                            from launcher.core import lifelog as _ll
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
def _ladder_json(model_tag):
    """model_tag 이 속한 사다리(현재~더 가벼운)를 설치된 모델만으로 JSON 화. 없으면 ''."""
    try:
        from ..models import model_roles as _mr
    except Exception:
        try:
            from launcher.models import model_roles as _mr
        except Exception:
            try:
                from launcher import model_roles as _mr
            except Exception:
                return ""
    import json as _jl
    _lad = None
    for _seq in getattr(_mr, "LADDERS", {}).values():
        _tags = [_m for _m, _ in _seq]
        if model_tag in _tags:
            _lad = _seq[_tags.index(model_tag):]
            break
    if not _lad:
        return ""
    try:
        _inst = set(_mr.installed_models()) if hasattr(_mr, "installed_models") else None
    except Exception:
        _inst = None
    _out = [[_m, float(_n)] for _m, _n in _lad if (_inst is None or _m in _inst)]
    return _jl.dumps(_out) if len(_out) >= 2 else ""


# PRIVACY_GUARD_v1: 개인정보 인터넷 개시 금지 조항 (system_message 에 append)
_PRIVACY_CLAUSE = (
    "\n\n[개인정보 보호 — 반드시 준수]\n"
    "사용자의 개인정보로 판단되는 어떤 요소도 인터넷·외부 서비스·원격 저장소로 전송, 게시, "
    "업로드, 공유하지 마십시오. 여기에는 이름, 주소, 전화번호, 이메일, 계정/아이디, 비밀번호, "
    "API 키·토큰, 결제·금융 정보, 주민등록·여권 등 식별번호, 로컬 파일 경로·파일 내용, "
    "시스템·네트워크 식별 정보(호스트명, 사용자명, IP, MAC 등), 위치 정보가 포함됩니다.\n"
    "웹 검색·API 요청·외부 전송이 필요할 때에도 이러한 개인정보를 쿼리·페이로드·URL 에 절대 "
    "포함하지 마십시오. 개인정보가 필요한 외부 작업은 수행하지 말고 사용자에게 위험을 알리고 "
    "확인을 받으십시오. 확신이 없으면 전송하지 않는 쪽을 선택하십시오."
)


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
    tor_proxy: bool = False,
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
        from launcher.core import user_data as _ud
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
        "-e", "AGENT_MODEL_LADDER=" + _ladder_json(model_tag),
    ]
    cmd += _state_mount + _state_env  # AGENT_STATE_PERSIST_v1

    # FOLDER_POLICY_v1: 상시 허용 폴더 마운트 (샌드박스는 그 외 경로 물리 차단)
    try:
        try:
            from .. import folder_policy as _fp
        except Exception:
            from launcher.agent import folder_policy as _fp
        for _h, _c in _fp.mounts_for():
            cmd += ["-v", _h + ":" + _c]
        # FOLDER_POLICY_OVERLAY_v1: 허용 상위 안의 '금지' 하위를 빈 tmpfs 로 가림
        if hasattr(_fp, "tmpfs_masks_for"):
            for _m in _fp.tmpfs_masks_for():
                cmd += ["--tmpfs", _m]
    except Exception:
        pass

    if tor_proxy:
        # AGENT_PROXY_CFG_v1: 주소 정본은 launcher/config.py 다.
        #   원본: _http  = "http://host.docker.internal:8118"
        #         _socks = "socks5h://host.docker.internal:9050"
        #   컨테이너 이름 경로는 --add-host/포트게시에 의존하지 않아 더 견고하다.
        try:
            from .. import config as _cfgN
            _http = _cfgN.tor_http_proxy()
            _socks = _cfgN.tor_socks_proxy()
        except Exception:
            _http = "http://llm_tor:8118"
            _socks = "socks5h://llm_tor:9050"
        _no = "host.docker.internal,localhost,127.0.0.1"
        for _pk in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            cmd += ["-e", _pk + "=" + _http]
        for _pk in ("ALL_PROXY", "all_proxy"):
            cmd += ["-e", _pk + "=" + _socks]
        cmd += ["-e", "NO_PROXY=" + _no, "-e", "no_proxy=" + _no]
    elif block_internet:
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
        "--system_message", profile_system_message + _PRIVACY_CLAUSE,  # PRIVACY_GUARD_v1
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
        "--system_message", profile_system_message + _PRIVACY_CLAUSE,  # PRIVACY_GUARD_v1
    ]
    if auto_run:
        cmd += ["--auto_run"]
    if extra_args:
        cmd += list(extra_args)
    return cmd


# ─────────────────────────────────────────────
#  HOST_TOR_ENV_v1: 호스트 인터프리터용 Tor 프록시 환경변수
# ─────────────────────────────────────────────
def build_tor_env(base=None):
    """호스트 직접 실행 프로세스에 Tor 프록시를 강제하는 환경변수 dict.

    - HTTP/HTTPS  -> Privoxy(127.0.0.1:8118) -> Tor  (urllib/requests 호환)
    - ALL_PROXY   -> socks5h://127.0.0.1:9050        (socks5h: 원격 DNS, 유출 차단)
    - NO_PROXY    -> 로컬 Ollama(127.0.0.1/localhost) 우회  (필수 — 없으면 모델 호출 실패)

    Args:
        base: 기존 env dict(예: OllamaService.env_vars()). None 이면 os.environ 복사.
    Returns:
        프록시 키가 병합된 새 dict(원본 불변).
    """
    import os as _os
    env = dict(base) if base is not None else _os.environ.copy()
    _hp, _sp = 8118, 9050
    try:
        try:
            from .. import tor_runtime as _tr
        except Exception:
            from launcher import tor_runtime as _tr
        _hp = int(getattr(_tr, "TOR_HTTP_PORT", 8118))
        _sp = int(getattr(_tr, "TOR_HOST_PORT", 9050))
    except Exception:
        _hp, _sp = 8118, 9050
    _http = "http://127.0.0.1:%d" % _hp
    _socks = "socks5h://127.0.0.1:%d" % _sp
    _no = "127.0.0.1,localhost,::1,host.docker.internal"
    try:
        try:
            from .. import config as _cfg
        except Exception:
            from launcher import config as _cfg
        _oh = str(getattr(_cfg, "OLLAMA_HOST", "") or "")
        if _oh and _oh not in _no:
            _no += "," + _oh
    except Exception:
        pass
    for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        env[_k] = _http
    for _k in ("ALL_PROXY", "all_proxy"):
        env[_k] = _socks
    for _k in ("NO_PROXY", "no_proxy"):
        env[_k] = _no
    return env


__all__ = [
    "AgentMessage",
    "UnifiedAgent",
    "build_sandbox_pipe_cmd",
    "build_host_pipe_cmd",
    "build_tor_env",
    "looks_like_vision_attempt",
    "LEVEL_STDOUT", "LEVEL_STDERR", "LEVEL_INFO",
    "LEVEL_WARN", "LEVEL_ERROR", "LEVEL_TERMINATED",
]
