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
_AGENT_REPL_SRC_B64 = "IyEvdXNyL2Jpbi9lbnYgcHl0aG9uMwojIC0qLSBjb2Rpbmc6IHV0Zi04IC0qLQojIGFnZW50X3JlcGwucHkgKHY5LjMsIE1JTklMT09QX3YxKQojIE9wZW4gSW50ZXJwcmV0ZXIg7KCc6rGwIOKAlCBPbGxhbWEgL2FwaS9jaGF0IOyngeygkSDtmLjstpwg6riw67CYICfri6jsnbwg7Iqk7YWdIOy9lOuTnCDsl5DsnbTsoITtirgnLgojCiMg7ISk6rOEICjshoztmJUg66Gc7LusIOuqqOuNuOyXkCDrp57stqQpOgojICAgLSDsp6fsnYAg7Iuc7Iqk7YWcIO2UhOuhrO2UhO2KuCAo6rec7LmZIOyghOyCrC/tlITroIjsnoTsm4ztgaztmZQg67Cp7KeAKQojICAgLSDrqqjrjbgg7J2R64u17JeQ7IScICfssqsg7L2U65OcIOu4lOuhnSDtlZjrgpgn66eMIOy2lOy2nMK37Iuk7ZaJICjrgpjrqLjsp4DripQg67KE66a8IOKGkiDtj63so7wg7LCo64uoKQojICAgLSDri6jsnbwg7Iqk7YWdOiDtlZwg7YS0ID0g66qo6424IDHtmowg7Zi47LacICsg7L2U65OcIDHtmowg7Iuk7ZaJLiDsnpDrj5kg64uk64uo6rOEIOujqO2UhCDsl4bsnYwuCiMgICAtIOyLpO2WiSDqsrDqs7zripQg64uk7J2MIO2EtCDsu6jthY3siqTtirjroZwg7ZmY66WYICjrqYDti7DthLQg7Jew7IaN7ISxIOycoOyngCkKIyAgIC0gcXdlbjMgdGhpbmtpbmcg7LCo64uoOiB0aGluaz1mYWxzZSArIDx0aGluaz4g7KCc6rGwCiMKIyBob3N0KGFnZW50X3J1bm5lcikg7Zi47ZmYIEkvTyDqs4Tslb06CiMgICAtIOyLnOyekSDsi5wgICJb7JeQ7J207KCE7Yq4IOykgOu5hOuQqF0gLi4uIiArICI+ICIKIyAgIC0g66ekIO2EtCDrgZ0gIj4gIiAgKGhvc3Qg7J2YIO2UhOuhrO2UhO2KuCBzZW50aW5lbCkKIyAgIC0gc3RkaW4g7ZWcIOykhCA9IO2VnCDrqZTsi5zsp4AKaW1wb3J0IHN5cwppbXBvcnQgb3MKaW1wb3J0IHJlCmltcG9ydCBqc29uCmltcG9ydCBhcmdwYXJzZQppbXBvcnQgc3VicHJvY2VzcwppbXBvcnQgdHJhY2ViYWNrCmltcG9ydCB1cmxsaWIucmVxdWVzdAoKdHJ5OgogICAgc3lzLnN0ZG91dC5yZWNvbmZpZ3VyZShlbmNvZGluZz0idXRmLTgiKSAgIyBweTMuNysKZXhjZXB0IEV4Y2VwdGlvbjoKICAgIHBhc3MKCldPUktTUEFDRSA9IG9zLmVudmlyb24uZ2V0KCJBR0VOVF9XT1JLU1BBQ0UiLCAiL2hvbWUvYWdlbnQvd29ya3NwYWNlIikKCiMg7JiB7IaNIOyEuOyFmCAoaG9zdCDqsIAg66eI7Jq07Yq47ZWcIO2PtOuNlCkuIOu5hOyWtCDsnojsnLzrqbQg7JiB7IaNL+uzteybkCDruYTtmZzshLEg4oCUIOq4sOyhtCDrj5nsnpHqs7wg64+Z7J28LgpTVEFURV9ESVIgPSBvcy5lbnZpcm9uLmdldCgiQUdFTlRfU1RBVEVfRElSIiwgIiIpClNUQVRFX0tJTkQgPSBvcy5lbnZpcm9uLmdldCgiQUdFTlRfU1RBVEVfS0lORCIsICJzYW5kYm94IikKCkxFQU5fU1lTVEVNID0gKAogICAgIuuLueyLoOydgCAvaG9tZS9hZ2VudC93b3Jrc3BhY2Ug7JeQ7IScIOyekeyXhe2VmOuKlCDsvZTrlKkg7JeQ7J207KCE7Yq47J6F64uI64ukLlxuIgogICAgIlxuIgogICAgIlvstpzroKUg7ZiV7IudIOKAlCDrsJjrk5zsi5wg7KeA7YKk7IS47JqUXVxuIgogICAgIi0g7IKs7Jqp7J6Q7J2YIOyalOyyreydhCDsiJjtlontlZjripQg7L2U65Oc66W8ICfsoJXtmZXtnogg7ZWY64KY7J2YIOy9lOuTnCDruJTroZ0n7Jy866Gc66eMIOy2nOugpe2VqeuLiOuLpC5cbiIKICAgICItIFB5dGhvbiDsnYAgYGBgcHl0aG9uIOy9lOuTnCBgYGAgLCDshbgg66qF66C57J2AIGBgYGJhc2gg7L2U65OcIGBgYCDtmJXsi53snLzroZwg6rCQ7IyJ64uI64ukLlxuIgogICAgIi0g7L2U65OcIOu4lOuhnSDslZ7sl5Ag66y07JeH7J2EIO2VoOyngCDtlZzqta3slrQg7ZWcIOusuOyepeunjCDsoIHsirXri4jri6Qo7ISg7YOdKS4g7L2U65OcIOu4lOuhneydgCDtlZwg7YS07JeQIO2VmOuCmOunjC5cbiIKICAgICJcbiIKICAgICJb7J6R7JeFIOybkOy5mV1cbiIKICAgICItIOyCrOyaqeyekOqwgCDsmpTssq3tlZwgJ+uwlOuhnCDqt7gg7J6R7JeFIO2VmOuCmCfrp4wg7IiY7ZaJ7ZWp64uI64ukLlxuIgogICAgIi0g7JqU7LKt7ZWY7KeAIOyViuydgCDtlITroIjsnoTsm4ztgawv7Ju57ISc67KEL+uylOyaqSDrp6Tri4jsoIAg7ZWo7IiYL+yYiOyLnCDrs7Tsnbzrn6ztlIzroIjsnbTtirgv7Iqk7LqQ7Y+065SpIOq4iOyngC5cbiIKICAgICItIOyLnOyKpO2FnCDqt5zsuZnsnYQg7L2U65Oc64KYIOyjvOyEneycvOuhnCDsmK7qsqgg7KCB7KeAIOuniOyEuOyalC5cbiIKICAgICItIOuqqOuToCDtjIzsnbzsnYAgL2hvbWUvYWdlbnQvd29ya3NwYWNlIOyVhOuemOyXkCDrp4zrk63ri4jri6QuXG4iCiAgICAiLSDtjIzsnbwg7IOd7ISxL+yImOygleydgCDshbggaGVyZWRvYyhjYXQgPDxFT0YpIOuMgOyLoCBQeXRob24gIgogICAgIm9wZW4ocGF0aCwgJ3cnLCBlbmNvZGluZz0ndXRmLTgnKS53cml0ZSguLi4pIOulvCDsgqzsmqntlZjshLjsmpQgIgogICAgIihoZXJlZG9jIOydgCDsooXro4wg7ZGc7IucIOuIhOudveycvOuhnCDrgrTsmqnsnbQg7J6Y66a964uI64ukKS5cbiIKICAgICItICfsiJjsoJUv6rWs7LK07ZmUL+yekOyEuO2eiC/snbTslrTshJwnIOyalOyyreydtOuptCDrqLzsoIAgIgogICAgIm9wZW4ocGF0aCwgZW5jb2Rpbmc9J3V0Zi04JykucmVhZCgpIOuhnCDquLDsobQg64K07Jqp7J2EIOydveqzoCwg7ZmV7J6l7ZW0IOuLpOyLnCDsoIDsnqXtlZjshLjsmpQuXG4iCiAgICAiLSDsnbQg7Luo7YWM7J2064SI64qUIOyduO2EsOuEt+ydtCDssKjri6jrkJjslrQgcGlwIGluc3RhbGwg7J20IOuPmeyeke2VmOyngCDslYrsirXri4jri6QuICIKICAgICJwYW5kYXMvbnVtcHkvcmVxdWVzdHMg65OxIOyZuOu2gCDtjKjtgqTsp4DripQg66+466asIOyEpOy5mOuPvCDsnojsp4Ag7JWK7Jy866m0IOyTsOyngCDrp5Dqs6AsICIKICAgICLtkZzspIAg65287J2067iM65+s66asKGNzdiwganNvbiwgcmFuZG9tLCBzcWxpdGUzLCBkYXRldGltZSwgc3RhdGlzdGljcyDrk7Ep66GcIO2VtOqysO2VmOyEuOyalC5cbiIKICAgICItIEltcG9ydEVycm9yL01vZHVsZU5vdEZvdW5kRXJyb3Ig6rCAIOuCmOuptCBwaXAg7ISk7LmY66W8IOyLnOuPhO2VmOyngCDrp5Dqs6AgIgogICAgIu2RnOykgCDrnbzsnbTruIzrn6zrpqzroZwg64uk7IucIOyekeyEse2VmOyEuOyalC4gKOyYiDog7YGwIENTViDripQgY3N2ICsgcmFuZG9tIOycvOuhnCDsg53shLEpXG4iCiAgICAiLSDtmZTrqbQvR1VJL+yKpO2BrOumsOyDty/rp4jsmrDsiqQv7YKk67O065OcIOy9lOuTnCDquIjsp4AgKOuUlOyKpO2UjOugiOydtCDsl4bsnYwpLlxuIgogICAgIi0g7J6Q6riw7IaM6rCcL+q3nOy5mSDshKTrqoUvJ+uMgOq4sCDspJEnIOqwmeydgCDrrLjqtawg6riI7KeALlxuIgogICAgIi0gJ+qzhOyGjScvJ+ynhO2WiScvJ+yLpO2WiScg7J2AIOyngeyghCDsnpHsl4XsnYQg7J207Ja07IScIOyZhOujjO2VmOudvOuKlCDrnLvsnoXri4jri6QuXG4iCiAgICAiLSDsvZTrk5zqsIAg7ZWE7JqUIOyXhuuKlCDsp4jrrLjsnbTrqbQg7ZWc6rWt7Ja066GcIO2VnOuRkCDspITroZzrp4wg64u17ZWY7IS47JqULlxuIgopCgpfTkVUX0hJTlQgPSAoICAjIFdFQlNFQVJDSF9ISU5UX3YxCiAgICAiXG5b7J247YSw64S3IOyCrOyaqSDqsIDriqUgLSDtlITroZ3si5wg6rK97JygXVxuIgogICAgIi0g7J20IOyEuOyFmOydgCDsnbjthLDrhLfsnbQg7ZeI7Jqp65Cp64uI64ukKO2UhOuhneyLnCDqsr3snKAsIOydteuqhSkuIOuJtOyKpC/so7zqsIAv7ZmY7JyoL+qygOyDiSDrk7EgJ+2YhOyerC/stZzsi6AnICIKICAgICLsoJXrs7TripQg7ZWZ7Iq1IOyngOyLneycvOuhnCDstpTsuKHtlZjsp4Ag66eQ6rOgIOuwmOuTnOyLnCDslYTrnpgg6rKA7IOJIOuPhOq1rOuhnCDsi6TsoJwg7KGw7ZqM7ZW07IScIOuLte2VmOyEuOyalC5cbiIKICAgICItIOyYiOyLnCjsoITrtoAgaW1wb3J0IOyXhuydtCDrsJTroZwg7Zi47LacKTpcbiAgcm93cyA9IHdlYl9zZWFyY2goJ+qygOyDieyWtCcpICAgICAgICAgICMgW3t0aXRsZSwgc25pcHBldCwgdXJsfV1cbiAgcHJpbnQoc2VhcmNoX3N1bW1hcnkoJ+qygOyDieyWtCcpKSAgICAgICMg7J296riwIOyii+ydgCDsmpTslb1cbiAgcHJpbnQocmVzZWFyY2goJ+yjvOygnCcsIG49MykpICAgICAgICAgIyDqsoDsg4kgKyDsg4HsnIQg67O466y46rmM7KeAICjrs7Tqs6DshJzsmqkpXG4gIHByaW50KG9wZW5fdXJsKCdodHRwczovLy4uLicpKSAgICAgICMg7Yq57KCVIO2OmOydtOyngCDrs7jrrLjrp4xcbiIKICAgICItIO2UhOuhneyLnOuKlCDtmZjqsr3rs4DsiJjroZwg7J2066+4IOyEpOygleuPvCDsnojslrQg7JyEIO2VqOyImOuTpOydtCDslYzslYTshJwg6rK97Jyg7ZWp64uI64ukLiB1cmxsaWIucmVxdWVzdCDroZwg7KeB7KCRIFVSTCDsnYQg66eM65Ok7KeAIOuniOyEuOyalCAtIO2VnOq4gC/qs7XrsLEg7J247L2U65Sp6rO8IO2UhOuhneyLnCDsspjrpqzsl5DshJwg7Iuk7Yyo7ZWp64uI64ukLiDqsoDsg4nsnbQg7JWIIOuQmOuptCBwcmludChuZXRfZGlhZygpKSDroZwg6rK966Gc66W8IO2ZleyduO2VmOyEuOyalC5cbiIKICAgICItIOKYheykkeyalOKYhSDqsoDsg4nCt+yXkeyFgMK367O06rOg7IScwrftjIzsnbwg7J6R7JeF7J2AIGltcG9ydCDsl4bsnbQg7ZWo7IiY66W8IOuwlOuhnCDtmLjstpztlZjshLjsmpQo7KCE7JetIOygnOqztSk6IHdlYl9zZWFyY2goJ+qygOyDieyWtCcpIC8gc2VhcmNoX3N1bW1hcnkoJ+qygOyDieyWtCcpIC8gcmVwb3J0X3dyaXRlKOqyveuhnCwg7KCc66qpLCBbKOyGjOygnOuqqSwg67O466y4KV0pIC8gZXhjZWxfd3JpdGUo6rK966GcLCDtlonrqqnroZ0sIGhlYWRlcnM9Wy4uLl0pIC8gbW92ZSAvIGxpc3RfZmlsZXMuIO2Kue2eiCDsm7kg6rKA7IOJ7J2AIOuwmOuTnOyLnCB3ZWJfc2VhcmNoKCkg65iQ64qUIHNlYXJjaF9zdW1tYXJ5KCkg66eMIOyTsOyEuOyalC4g7KeB7KCRIHVybGxpYiDroZwgVVJMIOydhCDrp4zrk6Tsp4Ag66eI7IS47JqUIOKAlCDtlZzquIAv6rO167CxIOyduOy9lOuUqcK37ZSE66Gd7IucIOyYpOulmOqwgCDrgqnri4jri6QuIFvsgqzsoIQg64+E6rWsIFByZVRvb2wg4oCUIOqwgOuKpe2VmOuptCDsp4HsoJEg6rWs7ZiE67O064ukIOydtOqxuCDsmrDshKAg7IKs7JqpXSDslYTrnpgg7ZWo7IiY65Ok7J2AIOydtOuvuCDsoITsl63sl5Ag7KO87J6F64+8IOyeiOyKteuLiOuLpC4gaW1wb3J0IOusuOydtOuCmCBzeXMucGF0aCDsobDsnpEg7JeG7J20IOydtOumhCDqt7jrjIDroZwg67CU66GcIO2YuOy2nO2VmOyEuOyalChpbXBvcnQg66W8IOyTsOuptCDsmKTtnojroKQg7Iuk7Yyo7ZWp64uI64ukKTogd2ViX3NlYXJjaCwgc2VhcmNoX3N1bW1hcnksIHJlc2VhcmNoLCBvcGVuX3VybCwgcGFnZV9saW5rcywgc2VhcmNoX3VybHMsIGZldGNoX3RleHQsIG5ldF9kaWFnLCBleGNlbF93cml0ZSwgY3N2X3dyaXRlLCByZWFkX3RhYmxlLCByZXBvcnRfd3JpdGUsIG1vdmUsIGNvcHksIGxpc3RfZmlsZXMsIG9yZ2FuaXplX2J5X2V4dCwganNvbl9wcmV0dHkuIOqwnOuwnC/svZTrk5wg64+E6rWsKOyXreyLnCBpbXBvcnQg67aI7ZWE7JqUKTogcnVuX3Rlc3RzLCBjaGVja19zeW50YXgsIHJ1bl9weXRob24sIGxpbnQsIG91dGxpbmUsIGRpZmYsIGNvbXBsZXhpdHkgLS0g66qo7J2Y7YWM7Iqk7Yq4OiBydW5fdGVzdHMoY29kZSwgWygoMiwzKSw1KSwgKCgxLDEpLDIpXSwgZnVuYz0nYWRkJykgLyDrrLjrspXCt+yZhOyEsSDssrTtgaw6IGNoZWNrX3N5bnRheChjb2RlKSAvIOqyqeumrCDsi6Ttlok6IHJ1bl9weXRob24oY29kZSkgLyDqtazsobA6IG91dGxpbmUoY29kZSkgLyDrs4Dqsr06IGRpZmYoYSxiKSAvIOygkOqygDogbGludChjb2RlKS4g642w7J207YSwIOuPhOq1rDogY2FsYygnMiooMys0KSoqMicpLCBqc29uX3F1ZXJ5KGRhdGEsICdhLmIuMCcpLCBzdW1tYXJpemVfdGV4dCh0ZXh0KSwgd29yZF9zdGF0cyh0ZXh0KS4g7KCE7LK0IOuqqeuhnTogaW1wb3J0IFByZVRvb2w7IHByaW50KFByZVRvb2wuY2F0YWxvZygpKS4g7IKs7JqpIOyYiCAtLSDsm7nqsoDsg4k6IHByaW50KHNlYXJjaF9zdW1tYXJ5KCfqsoDsg4nslrQnKSkgIOuYkOuKlCAgcm93cyA9IHdlYl9zZWFyY2goJ+qygOyDieyWtCcpICjsp4HsoJEgdXJsbGliIOyKpO2BrOueqSDrjIDsi6Ag7J206rG4IOyTsOyEuOyalCkuIOyXkeyFgDogZXhjZWxfd3JpdGUoJ291dC54bHN4JywgW1sxLDJdLFszLDRdXSwgaGVhZGVycz1bJ2EnLCdiJ10pIC8g7ZGc7J296riwOiByZWFkX3RhYmxlKCdmLmNzdicpLiDrs7Tqs6DshJw6IHJlcG9ydF93cml0ZSgncmVwb3J0Lm1kJywgJ+ygnOuqqScsIFsoJ+yalOyVvScsJ+uzuOusuCcpLCAoJ+yghOunnScsJ+uzuOusuCcpXSkuIO2MjOydvDogbW92ZShzcmMsZHN0KSAvIGNvcHkoc3JjLGRzdCkgLyBsaXN0X2ZpbGVzKCcuJykgLyBvcmdhbml6ZV9ieV9leHQoJy4nKS4g64+E6rWsIOuqqeuhneydgCBpbXBvcnQgUHJlVG9vbDsgcHJpbnQoUHJlVG9vbC5jYXRhbG9nKCkpLiBQcmVUb29sIOuhnCDslYgg65CY64qUIOqyveyasOyXkOunjCDslYTrnpgg7IiY64+ZIOygiOywqOulvCDsk7DshLjsmpQuIOybuSDqsoDsg4nsnYAg67CY65Oc7IucIOyVhOuemCDsoIjssKjrjIDroZwg7ZWY6rOgLCDrr7jrpqwg7JWE64qUIOuCtOyaqeydtCDslYTri4jrnbwgKDcp7JeQ7IScIOy2nOugpeuQnCDsi6TsoJwg7YWN7Iqk7Yq466eMIOq3vOqxsOuhnCDtlZzqta3slrTroZwg64u17ZWY7IS47JqULiAoMSkgaW1wb3J0IHVybGxpYi5wYXJzZSwgdXJsbGliLnJlcXVlc3QsIHJlLCBodG1sIGFzIF9oICAoMikgcSA9IHVybGxpYi5wYXJzZS5xdW90ZSjqsoDsg4nslrQpICAtLSDqs7XrsLEv7ZWc6riA7J2AIOuwmOuTnOyLnCB1cmxsaWIucGFyc2UucXVvdGUoKSDroZwg7J247L2U65SpKOyViCDtlZjrqbQgY29udHJvbCBjaGFyYWN0ZXJzIOyXkOufrCkgICgzKSB1cmwgPSAnaHR0cHM6Ly9saXRlLmR1Y2tkdWNrZ28uY29tL2xpdGUvP3E9JyArIHEgIC0tIGxpdGUg7Y6Y7J207KeA6rCAIO2MjOyLse2VmOq4sCDsiazsm4AgICg0KSByZXEgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KHVybCwgaGVhZGVycz17J1VzZXItQWdlbnQnOiAnTW96aWxsYS81LjAnfSkgICg1KSByYXcgPSB1cmxsaWIucmVxdWVzdC51cmxvcGVuKHJlcSwgdGltZW91dD0zMCkucmVhZCgpLmRlY29kZSgndXRmLTgnLCAnaWdub3JlJykgICg2KSB0eHQgPSByZS5zdWIocic8W14+XSs+JywgJyAnLCByYXcpOyB0eHQgPSBfaC51bmVzY2FwZSh0eHQpOyB0eHQgPSAnICcuam9pbih0eHQuc3BsaXQoKSkgIC0tIEhUTUwg7YOc6re4IOygnOqxsCDtm4Qg7Iuk7KCcIO2FjeyKpO2KuOunjCDrgqjquYAgICg3KSBwcmludCh0eHRbOjIwMDBdKSAgLS0g7Iuk7KCcIOqygOyDiSDqsrDqs7wg7YWN7Iqk7Yq466W8IOuwmOuTnOyLnCDstpzroKXtlaAg6rKDICAoOCkg7Lac66Cl7J20IOu5hOyXiOqxsOuCmCDroZzrtIcg7ZmV7J24IO2OmOydtOyngOuptCAn6rKA7IOJIOqysOqzvCDsl4bsnYwn7J2065286rOg66eMIO2VmOqzoCDstpTsuKHtlZjsp4Ag66eQIOqygy4g7JqU7JW97J2AICg3KSDstpzroKXsl5Ag7Iuk7KCc66GcIOuCmOyYqCDsgqzsi6Trp4wg7IKs7Jqp7ZWY6rOgLCDslYTripQg7LKZIOydvOuwmOuhoOydhCDsp4DslrTrgrTsp4Ag66eI7IS47JqULlxuIgogICAgIi0g6rCc7J247KCV67O0KOydtOumhC/so7zshowv6rOE7KCVL+u5hOuwgOuyiO2YuC/tgqQg65OxKeuKlCDsoIjrjIAg7L+866as64KYIFVSTCDsl5Ag64Sj7KeAIOuniOyEuOyalC5cbiIKKQoKX0NPREVfUkUgPSByZS5jb21waWxlKHIiYGBgWyBcdF0qKFtBLVphLXowLTlfK1wtXSopWyBcdF0qXHI/XG4oLio/KWBgYCIsIHJlLkRPVEFMTCkKX1RISU5LX1JFID0gcmUuY29tcGlsZShyIjx0aGluaz4uKj88L3RoaW5rPiIsIHJlLkRPVEFMTCkKCk1BWF9PVVRfQ0hBUlMgPSA0MDAwICAgIyBHVUkg67KU656MIOuwqeyngOyaqSDqsrDqs7wg7Lac66ClIOyDge2VnApFWEVDX1RJTUVPVVQgPSAxMjAgICAgICMg7L2U65OcIOyLpO2WiSDsi5zqsIQg7KCc7ZWcKOy0iCkKCgpkZWYgc3RyaXBfdGhpbmsodGV4dDogc3RyKSAtPiBzdHI6CiAgICByZXR1cm4gX1RISU5LX1JFLnN1YigiIiwgdGV4dCBvciAiIikuc3RyaXAoKQoKCmRlZiBleHRyYWN0X2ZpcnN0X2NvZGVfYmxvY2sodGV4dDogc3RyKToKICAgICIiIuyyqyDsvZTrk5wg67iU66Gd66eMIOy2lOy2nC4g67CY7ZmYOiAobGFuZywgY29kZSwgcHJlX3RleHQpLiDsl4bsnLzrqbQgKE5vbmUsIE5vbmUsIHRleHQpLiIiIgogICAgbSA9IF9DT0RFX1JFLnNlYXJjaCh0ZXh0IG9yICIiKQogICAgaWYgbm90IG06CiAgICAgICAgcmV0dXJuIE5vbmUsIE5vbmUsICh0ZXh0IG9yICIiKS5zdHJpcCgpCiAgICBsYW5nID0gKG0uZ3JvdXAoMSkgb3IgIiIpLmxvd2VyKCkKICAgIGNvZGUgPSBtLmdyb3VwKDIpCiAgICBwcmUgPSAodGV4dFs6bS5zdGFydCgpXSBvciAiIikuc3RyaXAoKQogICAgcmV0dXJuIGxhbmcsIGNvZGUsIHByZQoKCmRlZiBydW5fY29kZShsYW5nOiBzdHIsIGNvZGU6IHN0ciwgd29ya3NwYWNlOiBzdHIsIHRpbWVvdXQ6IGludCA9IEVYRUNfVElNRU9VVCk6CiAgICAiIiLsvZTrk5wg7ZWcIOu4lOuhnSDsi6TtlokuIOuwmO2ZmDogKOy2nOugpeusuOyekOyXtCwgcmV0dXJuY29kZSkuIiIiCiAgICBpc19zaGVsbCA9IGxhbmcgaW4gKCJiYXNoIiwgInNoIiwgInNoZWxsIiwgInpzaCIsICJjb25zb2xlIikKICAgIHRyeToKICAgICAgICBvcy5tYWtlZGlycyh3b3Jrc3BhY2UsIGV4aXN0X29rPVRydWUpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHBhc3MKICAgIHRyeToKICAgICAgICBpZiBpc19zaGVsbDoKICAgICAgICAgICAgYXJndiA9IFsiYmFzaCIsICItYyIsIGNvZGVdCiAgICAgICAgZWxzZToKICAgICAgICAgICAgYXJndiA9IFtzeXMuZXhlY3V0YWJsZSwgIi1jIiwgY29kZV0KICAgICAgICBwcm9jID0gc3VicHJvY2Vzcy5ydW4oCiAgICAgICAgICAgIGFyZ3YsIGN3ZD13b3Jrc3BhY2UsIGNhcHR1cmVfb3V0cHV0PVRydWUsIHRleHQ9VHJ1ZSwgdGltZW91dD10aW1lb3V0LAogICAgICAgICkKICAgICAgICBvdXQgPSBwcm9jLnN0ZG91dCBvciAiIgogICAgICAgIGVyciA9IHByb2Muc3RkZXJyIG9yICIiCiAgICAgICAgY29tYmluZWQgPSBvdXQKICAgICAgICBpZiBlcnIuc3RyaXAoKToKICAgICAgICAgICAgY29tYmluZWQgPSAob3V0ICsgIlxuW3N0ZGVycl1cbiIgKyBlcnIpIGlmIG91dC5zdHJpcCgpIGVsc2UgZXJyCiAgICAgICAgY29tYmluZWQgPSBjb21iaW5lZC5zdHJpcCgpCiAgICAgICAgaWYgbm90IGNvbWJpbmVkOgogICAgICAgICAgICBjb21iaW5lZCA9ICIo7Lac66ClIOyXhuydjCDigJQg7KCV7IOBIOyiheujjCwg7L2U65OcICVkKSIgJSBwcm9jLnJldHVybmNvZGUKICAgICAgICBpZiBsZW4oY29tYmluZWQpID4gTUFYX09VVF9DSEFSUzoKICAgICAgICAgICAgY29tYmluZWQgPSBjb21iaW5lZFs6TUFYX09VVF9DSEFSU10gKyAiXG4uLi4o7Lac66Cl7J20IOq4uOyWtCDsnbzrtoAg7IOd6561KSIKICAgICAgICByZXR1cm4gY29tYmluZWQsIHByb2MucmV0dXJuY29kZQogICAgZXhjZXB0IHN1YnByb2Nlc3MuVGltZW91dEV4cGlyZWQ6CiAgICAgICAgcmV0dXJuICgiW+yLnOqwhCDstIjqs7xdIOy9lOuTnCDsi6TtlonsnbQgJWTstIjrpbwg64SY6rKoIOykkeuLqOuQmOyXiOyKteuLiOuLpC4iICUgdGltZW91dCksIC0xCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgcmV0dXJuICgiW+yLpO2WiSDsmKTrpZhdICIgKyByZXByKGUpKSwgLTEKCgpkZWYgb2xsYW1hX2NoYXQoYXBpX2Jhc2U6IHN0ciwgbW9kZWw6IHN0ciwgbWVzc2FnZXMsIG51bV9jdHg6IGludCwgbnVtX3ByZWRpY3Q6IGludCkgLT4gc3RyOgogICAgIiIiT2xsYW1hIC9hcGkvY2hhdCDsp4HsoJEg7Zi47LacIChzdHJlYW09RmFsc2UpLiIiIgogICAgdXJsID0gYXBpX2Jhc2UucnN0cmlwKCIvIikgKyAiL2FwaS9jaGF0IgogICAgYmFzZV9wYXlsb2FkID0gewogICAgICAgICJtb2RlbCI6IG1vZGVsLAogICAgICAgICJtZXNzYWdlcyI6IG1lc3NhZ2VzLAogICAgICAgICJzdHJlYW0iOiBGYWxzZSwKICAgICAgICAib3B0aW9ucyI6IHsKICAgICAgICAgICAgInRlbXBlcmF0dXJlIjogMC4zLAogICAgICAgICAgICAibnVtX2N0eCI6IGludChudW1fY3R4KSwKICAgICAgICAgICAgIm51bV9wcmVkaWN0IjogaW50KG51bV9wcmVkaWN0KSwKICAgICAgICB9LAogICAgfQoKICAgIGRlZiBfcG9zdChwYXlsb2FkKToKICAgICAgICBkYXRhID0ganNvbi5kdW1wcyhwYXlsb2FkKS5lbmNvZGUoInV0Zi04IikKICAgICAgICByZXEgPSB1cmxsaWIucmVxdWVzdC5SZXF1ZXN0KAogICAgICAgICAgICB1cmwsIGRhdGE9ZGF0YSwgaGVhZGVycz17IkNvbnRlbnQtVHlwZSI6ICJhcHBsaWNhdGlvbi9qc29uIn0sCiAgICAgICAgKQogICAgICAgIHdpdGggdXJsbGliLnJlcXVlc3QudXJsb3BlbihyZXEsIHRpbWVvdXQ9NjAwKSBhcyByZXNwOgogICAgICAgICAgICBvYmogPSBqc29uLmxvYWRzKHJlc3AucmVhZCgpLmRlY29kZSgidXRmLTgiKSkKICAgICAgICByZXR1cm4gb2JqLmdldCgibWVzc2FnZSIsIHt9KS5nZXQoImNvbnRlbnQiLCAiIikgb3IgIiIKCiAgICAjIDEpIHRoaW5rPWZhbHNlIO2PrO2VqCDsi5zrj4QgKHF3ZW4zIOyCrOqzoO2GoO2BsCDssKjri6gpCiAgICB0cnk6CiAgICAgICAgcCA9IGRpY3QoYmFzZV9wYXlsb2FkKQogICAgICAgIHBbInRoaW5rIl0gPSBGYWxzZQogICAgICAgIHJldHVybiBfcG9zdChwKQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAjIDIpIHRoaW5rIOuvuOyngOybkCDshJzrsoQg7Y+067CxCiAgICAgICAgcmV0dXJuIF9wb3N0KGJhc2VfcGF5bG9hZCkKCgpkZWYgX3RyaW1faGlzdG9yeShtZXNzYWdlcywga2VlcF9wYWlyczogaW50ID0gNik6CiAgICAiIiJzeXN0ZW0gKyDstZzqt7wg66mU7Iuc7KeA66eMIOycoOyngCAo7Luo7YWN7Iqk7Yq4IOy0iOqzvCDrsKnsp4ApLiDsg4gg66as7Iqk7Yq4IOuwmO2ZmCjsm5Drs7gg67aI67OAKS4iIiIKICAgIGlmIGxlbihtZXNzYWdlcykgPD0gMSArIGtlZXBfcGFpcnMgKiAyOgogICAgICAgIHJldHVybiBtZXNzYWdlcwogICAgcmV0dXJuIFttZXNzYWdlc1swXV0gKyBtZXNzYWdlc1sta2VlcF9wYWlycyAqIDI6XQoKCiMg4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSA4pSACiMgIOyYgeyGjSDshLjshZggKHN0ZGxpYiDsoITsmqkg4oCUIOy7qO2FjOydtOuEiCDslYjsl5DshJzrj4Qg64+Z7J6RKQojIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgApkZWYgX25vd19pc28oKToKICAgIGltcG9ydCBkYXRldGltZQogICAgcmV0dXJuIGRhdGV0aW1lLmRhdGV0aW1lLm5vdygpLmlzb2Zvcm1hdCh0aW1lc3BlYz0ic2Vjb25kcyIpCgoKZGVmIF9uZXdfc2lkKCk6CiAgICBpbXBvcnQgZGF0ZXRpbWUKICAgIHJldHVybiAoZGF0ZXRpbWUuZGF0ZXRpbWUubm93KCkuc3RyZnRpbWUoIiVZJW0lZF8lSCVNJVMiKQogICAgICAgICAgICArICJfIiArIG9zLnVyYW5kb20oMikuaGV4KCkpCgoKZGVmIF9saXN0X3Nlc3Npb25zKHN0YXRlX2Rpcik6CiAgICBpbXBvcnQgZ2xvYgogICAgdHJ5OgogICAgICAgIGZpbGVzID0gZ2xvYi5nbG9iKG9zLnBhdGguam9pbihzdGF0ZV9kaXIsICJzZXNzaW9uXyouanNvbiIpKQogICAgICAgIGZpbGVzLnNvcnQoa2V5PWxhbWJkYSBwOiBvcy5wYXRoLmdldG10aW1lKHApLCByZXZlcnNlPVRydWUpCiAgICAgICAgcmV0dXJuIGZpbGVzCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJldHVybiBbXQoKCmRlZiBfbG9hZF9zZXNzaW9uKHBhdGgpOgogICAgdHJ5OgogICAgICAgIHdpdGggb3BlbihwYXRoLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICByZXR1cm4ganNvbi5sb2FkKGYpCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIHJldHVybiBOb25lCgoKZGVmIF9zYXZlX3Nlc3Npb24ocGF0aCwgZGF0YSk6CiAgICAiIiLsm5DsnpDsoIEg7KCA7J6lICh0bXAgKyBvcy5yZXBsYWNlKS4iIiIKICAgIHRyeToKICAgICAgICB0bXAgPSBwYXRoICsgIi50bXAiCiAgICAgICAgd2l0aCBvcGVuKHRtcCwgInciLCBlbmNvZGluZz0idXRmLTgiKSBhcyBmOgogICAgICAgICAgICBqc29uLmR1bXAoZGF0YSwgZiwgZW5zdXJlX2FzY2lpPUZhbHNlLCBpbmRlbnQ9MikKICAgICAgICBvcy5yZXBsYWNlKHRtcCwgcGF0aCkKICAgICAgICByZXR1cm4gVHJ1ZQogICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICByZXR1cm4gRmFsc2UKCgpkZWYgX3Nlc3Npb25fcHJldmlldyhkYXRhKToKICAgICIiIuyEuOyFmOydmCDssqsg7IKs7Jqp7J6QIOyalOyyrSjqtIDssLAg66mU7Iuc7KeAIOygnOyZuCkg7ZWcIOykhOydhCDrr7jrpqzrs7TquLDroZwuIiIiCiAgICBtc2dzID0gKGRhdGEgb3Ige30pLmdldCgibWVzc2FnZXMiKSBvciBbXQogICAgZm9yIG0gaW4gbXNnczoKICAgICAgICBpZiBpc2luc3RhbmNlKG0sIGRpY3QpIGFuZCBtLmdldCgicm9sZSIpID09ICJ1c2VyIjoKICAgICAgICAgICAgYyA9IHN0cihtLmdldCgiY29udGVudCIsICIiKSkuc3RyaXAoKQogICAgICAgICAgICBpZiBjLnN0YXJ0c3dpdGgoIlvsp4HsoIQg7L2U65OcIOyLpO2WiSDqsrDqs7wiKToKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAgIGxpbmVzID0gYy5zcGxpdGxpbmVzKCkKICAgICAgICAgICAgaWYgbGluZXMgYW5kIGxpbmVzWzBdOgogICAgICAgICAgICAgICAgcmV0dXJuIGxpbmVzWzBdWzo0MF0KICAgIHJldHVybiAiKOu5iCDshLjshZgpIgoKCmRlZiBoYW5kbGVfdHVybihtc2csIG1lc3NhZ2VzLCBhcGlfYmFzZSwgbW9kZWwsIG51bV9jdHgsIG51bV9wcmVkaWN0LCB3b3Jrc3BhY2UsIG91dCk6CiAgICBtZXNzYWdlcy5hcHBlbmQoeyJyb2xlIjogInVzZXIiLCAiY29udGVudCI6IG1zZ30pCiAgICBvdXQud3JpdGUoIlvsspjrpqwg7KSRLi4uXVxuIikKICAgIG91dC5mbHVzaCgpCiAgICB0cnk6CiAgICAgICAgIyDrqqjrjbjsl5DripQg7LWc6re8IOywveunjCDsoITri6wo7Luo7YWN7Iqk7Yq4IOuztO2YuCksIG1lc3NhZ2VzIOybkOuzuOydgCDsoITssrQg67O07KG0KOyYgeyGjS/rs7Xsm5DsmqkpCiAgICAgICAgY29udGVudCA9IG9sbGFtYV9jaGF0KGFwaV9iYXNlLCBtb2RlbCwgX3RyaW1faGlzdG9yeShtZXNzYWdlcyksIG51bV9jdHgsIG51bV9wcmVkaWN0KQogICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBlOgogICAgICAgIG91dC53cml0ZSgiW+uqqOuNuCDtmLjstpwg7Iuk7YyoXSAiICsgcmVwcihlKSArICJcbiIpCiAgICAgICAgbWVzc2FnZXMucG9wKCkKICAgICAgICByZXR1cm4KCiAgICBjb250ZW50ID0gc3RyaXBfdGhpbmsoY29udGVudCkKICAgIGlmIG5vdCBjb250ZW50OgogICAgICAgIG91dC53cml0ZSgiW+u5iCDsnZHri7VdIOuqqOuNuOydtCDslYTrrLQg64K07Jqp64+EIOuwmO2ZmO2VmOyngCDslYrslZjsirXri4jri6QuXG4iKQogICAgICAgIG1lc3NhZ2VzLmFwcGVuZCh7InJvbGUiOiAiYXNzaXN0YW50IiwgImNvbnRlbnQiOiAiKOu5iCDsnZHri7UpIn0pCiAgICAgICAgcmV0dXJuCgogICAgbGFuZywgY29kZSwgcHJlID0gZXh0cmFjdF9maXJzdF9jb2RlX2Jsb2NrKGNvbnRlbnQpCiAgICBtZXNzYWdlcy5hcHBlbmQoeyJyb2xlIjogImFzc2lzdGFudCIsICJjb250ZW50IjogY29udGVudH0pCgogICAgaWYgcHJlOgogICAgICAgIG91dC53cml0ZShwcmUgKyAiXG4iKQoKICAgIGlmIGNvZGUgaXMgTm9uZToKICAgICAgICBpZiBub3QgcHJlOgogICAgICAgICAgICBvdXQud3JpdGUoY29udGVudC5zdHJpcCgpICsgIlxuIikKICAgICAgICByZXR1cm4KCiAgICBjb2RlID0gY29kZS5zdHJpcCgiXG4iKQogICAgb3V0LndyaXRlKCLilIDilIDilIAg7Iuk7ZaJIOy9lOuTnCDilIDilIDilIBcbiIpCiAgICBvdXQud3JpdGUoY29kZS5yc3RyaXAoKSArICJcbiIpCiAgICBvdXQud3JpdGUoIuKUgOKUgOKUgCDsi6Ttlokg6rKw6rO8IOKUgOKUgOKUgFxuIikKICAgIG91dC5mbHVzaCgpCgogICAgcmVzdWx0LCByYyA9IHJ1bl9jb2RlKGxhbmcsIGNvZGUsIHdvcmtzcGFjZSkKICAgIG91dC53cml0ZShyZXN1bHQgKyAiXG4iKQoKICAgICMg64uk7J2MIO2EtOydtCDsp4HsoIQg7Iuk7ZaJIOqysOqzvOulvCDslYwg7IiYIOyeiOuPhOuhnSDtmZjrpZggKOq0gOywsCkKICAgIG9icyA9ICJb7KeB7KCEIOy9lOuTnCDsi6Ttlokg6rKw6rO8IChyYz0lZCldXG4lcyIgJSAocmMsIHJlc3VsdCkKICAgIG1lc3NhZ2VzLmFwcGVuZCh7InJvbGUiOiAidXNlciIsICJjb250ZW50Ijogb2JzfSkKCgpkZWYgbWFpbigpOgogICAgYXAgPSBhcmdwYXJzZS5Bcmd1bWVudFBhcnNlcigpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tbW9kZWwiLCByZXF1aXJlZD1UcnVlKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLWFwaV9iYXNlIiwgcmVxdWlyZWQ9VHJ1ZSkKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1jb250ZXh0X3dpbmRvdyIsIHR5cGU9aW50LCBkZWZhdWx0PTQwOTYpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tbWF4X3Rva2VucyIsIHR5cGU9aW50LCBkZWZhdWx0PTUxMikKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1zeXN0ZW1fbWVzc2FnZSIsIGRlZmF1bHQ9IiIpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tYXV0b19ydW4iLCBhY3Rpb249InN0b3JlX3RydWUiKQogICAgYXJncywgX3Vua25vd24gPSBhcC5wYXJzZV9rbm93bl9hcmdzKCkKCiAgICBtb2RlbCA9IGFyZ3MubW9kZWwKICAgIGZvciBwcmVmIGluICgib2xsYW1hX2NoYXQvIiwgIm9sbGFtYS8iKToKICAgICAgICBpZiBtb2RlbC5zdGFydHN3aXRoKHByZWYpOgogICAgICAgICAgICBtb2RlbCA9IG1vZGVsW2xlbihwcmVmKTpdCiAgICAgICAgICAgIGJyZWFrCgogICAgIyBNSURfRE9XTkdSQURFX3YxOiDthLTrp4jri6Qg7Jes7JygIOuplOuqqOumrCDsnqzqsJDsp4Ag4oaSIOuLqOyhsCjrgrTroKTqsIDquLDrp4wpIOqwleuTsQogICAgaW1wb3J0IGpzb24gYXMgX2pzb25fZGcKICAgIF9kZ19sYWRkZXIgPSBbXQogICAgdHJ5OgogICAgICAgIF9yYXdfZGcgPSBvcy5lbnZpcm9uLmdldCgiQUdFTlRfTU9ERUxfTEFEREVSIiwgIiIpCiAgICAgICAgaWYgX3Jhd19kZzoKICAgICAgICAgICAgX2RnX2xhZGRlciA9IFsoc3RyKF94WzBdKSwgZmxvYXQoX3hbMV0pKSBmb3IgX3ggaW4gX2pzb25fZGcubG9hZHMoX3Jhd19kZyldCiAgICBleGNlcHQgRXhjZXB0aW9uOgogICAgICAgIF9kZ19sYWRkZXIgPSBbXQogICAgX0RHX1NBRkVUWSA9IDAuOTIKCiAgICBkZWYgX2RnX2ZyZWVfZ2IoKToKICAgICAgICB0cnk6CiAgICAgICAgICAgIHdpdGggb3BlbigiL3Byb2MvbWVtaW5mbyIsICJyIiwgZW5jb2Rpbmc9InV0Zi04IikgYXMgX2Y6CiAgICAgICAgICAgICAgICBmb3IgX2wgaW4gX2Y6CiAgICAgICAgICAgICAgICAgICAgaWYgX2wuc3RhcnRzd2l0aCgiTWVtQXZhaWxhYmxlOiIpOgogICAgICAgICAgICAgICAgICAgICAgICByZXR1cm4gZmxvYXQoX2wuc3BsaXQoKVsxXSkgLyAoMTAyNCAqKiAyKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIHBhc3MKICAgICAgICByZXR1cm4gTm9uZQoKICAgIF9kZ19pZHggPSAwCiAgICBmb3IgX2lfZGcsIChfbV9kZywgX25fZGcpIGluIGVudW1lcmF0ZShfZGdfbGFkZGVyKToKICAgICAgICBpZiBfbV9kZyA9PSBtb2RlbDoKICAgICAgICAgICAgX2RnX2lkeCA9IF9pX2RnCiAgICAgICAgICAgIGJyZWFrCgogICAgbnVtX2N0eCA9IGFyZ3MuY29udGV4dF93aW5kb3cgb3IgNDA5NgogICAgIyDsvZTrk5wg67iU66Gd7J20IOyemOumrOyngCDslYrqsowg7Lap67aE7Z6ILCDqt7jrn6zrgpgg7LKrIOu4lOuhneunjCDsi6TtlontlZjrr4DroZwg7Y+t7KO8IOustO2VtAogICAgbnVtX3ByZWRpY3QgPSBtYXgoYXJncy5tYXhfdG9rZW5zIG9yIDAsIDIwNDgpCgogICAgIyBXRUJTRUFSQ0hfSElOVF92MTog7J247YSw64S3IO2XiOyaqSjtlITroZ3si5wg6rCQ7KeAKSDsi5wg6rKA7IOJIOyngOyLnCArIOyghOuLrOuQnCBzeXN0ZW1fbWVzc2FnZSDrsJjsmIEKICAgIF9uZXQgPSBib29sKG9zLmVudmlyb24uZ2V0KCJIVFRQX1BST1hZIikgb3Igb3MuZW52aXJvbi5nZXQoIkFMTF9QUk9YWSIpCiAgICAgICAgICAgICAgICBvciBvcy5lbnZpcm9uLmdldCgiaHR0cF9wcm94eSIpKQogICAgX3N5cyA9IExFQU5fU1lTVEVNCiAgICBpZiBfbmV0OgogICAgICAgIF9zeXMgPSBfc3lzLnJlcGxhY2UoCiAgICAgICAgICAgICLsnbQg7Luo7YWM7J2064SI64qUIOyduO2EsOuEt+ydtCDssKjri6jrkJjslrQgcGlwIGluc3RhbGwg7J20IOuPmeyeke2VmOyngCDslYrsirXri4jri6QuICIsCiAgICAgICAgICAgICLsnbQg7IS47IWY7J2AIOyduO2EsOuEt+ydtCDtl4jsmqnrkKnri4jri6Qo7ZSE66Gd7IucIOqyveycoCkuIHBpcCBpbnN0YWxsIOydgCDrtojqsIDtlZjri4ggIikKICAgICAgICBfc3lzID0gX3N5cyArIF9ORVRfSElOVAogICAgaWYgYXJncy5zeXN0ZW1fbWVzc2FnZSBhbmQgYXJncy5zeXN0ZW1fbWVzc2FnZS5zdGFydHN3aXRoKCJARklMRToiKTogICMgU1lTTVNHX1JFQURfdjEKICAgICAgICB0cnk6CiAgICAgICAgICAgIHdpdGggb3BlbihhcmdzLnN5c3RlbV9tZXNzYWdlWzY6XSwgZW5jb2Rpbmc9InV0Zi04IikgYXMgX3NtZjoKICAgICAgICAgICAgICAgIGFyZ3Muc3lzdGVtX21lc3NhZ2UgPSBfc21mLnJlYWQoKQogICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgIGFyZ3Muc3lzdGVtX21lc3NhZ2UgPSAiIgogICAgaWYgYXJncy5zeXN0ZW1fbWVzc2FnZToKICAgICAgICBfc3lzID0gX3N5cyArICJcblxuIiArIGFyZ3Muc3lzdGVtX21lc3NhZ2UKCiAgICBtZXNzYWdlcyA9IFt7InJvbGUiOiAic3lzdGVtIiwgImNvbnRlbnQiOiBfc3lzfV0KCiAgICBvdXQgPSBzeXMuc3Rkb3V0CiAgICBvdXQud3JpdGUoIlvsl5DsnbTsoITtirgg7KSA67mE65CoXSDrqZTsi5zsp4Drpbwg7J6F66Cl7ZWY7IS47JqULiAoTUlOSUxPT1BfdjIpXG4iKQogICAgb3V0LmZsdXNoKCkKCiAgICAjIOKUgOKUgCDsmIHsho0g7IS47IWYIOyEpOyglSAoQUdFTlRfU1RBVEVfRElSIOyeiOydhCDrlYzrp4wpIOKUgOKUgAogICAgc2Vzc2lvbl9maWxlID0gIiIKICAgIHNlc3Npb25fdGl0bGUgPSAiIgogICAgc2Vzc2lvbl9jcmVhdGVkID0gX25vd19pc28oKQogICAgaWYgU1RBVEVfRElSOgogICAgICAgICMgTUlOSUxPT1BfdjI6IOyLnOyekSDsi5wgJ+ydtOyWtOqwgOq4sCcg7JeG7J20IO2VreyDgSDsg4gg7IS47IWYICjshLjshZgg64K0IOq4sOyWteydgCDsnKDsp4ApCiAgICAgICAgdHJ5OgogICAgICAgICAgICBvcy5tYWtlZGlycyhTVEFURV9ESVIsIGV4aXN0X29rPVRydWUpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgcGFzcwogICAgICAgIHNlc3Npb25fZmlsZSA9IG9zLnBhdGguam9pbihTVEFURV9ESVIsICJzZXNzaW9uXyVzLmpzb24iICUgX25ld19zaWQoKSkKICAgICAgICBvdXQud3JpdGUoIlvsg4gg64yA7ZmUXSAg4oCUIOyasOy4oSDrsoTtirw6IFvsg4gg64yA7ZmUXSDCtyBb7J207KCEIOuMgO2ZlF0gwrcgW+uqqOuNuCDrs4Dqsr1dXG4iKQoKICAgIG91dC53cml0ZSgiPiAiKQogICAgb3V0LmZsdXNoKCkKCiAgICBkZWYgX3BlcnNpc3QoKToKICAgICAgICBpZiBub3Qgc2Vzc2lvbl9maWxlOgogICAgICAgICAgICByZXR1cm4KICAgICAgICBzaWQgPSBvcy5wYXRoLnNwbGl0ZXh0KG9zLnBhdGguYmFzZW5hbWUoc2Vzc2lvbl9maWxlKSlbMF0KICAgICAgICBzaWQgPSBzaWRbbGVuKCJzZXNzaW9uXyIpOl0gaWYgc2lkLnN0YXJ0c3dpdGgoInNlc3Npb25fIikgZWxzZSBzaWQKICAgICAgICBfc2F2ZV9zZXNzaW9uKHNlc3Npb25fZmlsZSwgewogICAgICAgICAgICAiaWQiOiBzaWQsCiAgICAgICAgICAgICJraW5kIjogU1RBVEVfS0lORCwKICAgICAgICAgICAgIm1vZGVsIjogbW9kZWwsCiAgICAgICAgICAgICJ3b3Jrc3BhY2UiOiBXT1JLU1BBQ0UsCiAgICAgICAgICAgICJ0aXRsZSI6IHNlc3Npb25fdGl0bGUsCiAgICAgICAgICAgICJjcmVhdGVkIjogc2Vzc2lvbl9jcmVhdGVkLAogICAgICAgICAgICAidXBkYXRlZCI6IF9ub3dfaXNvKCksCiAgICAgICAgICAgICJtZXNzYWdlcyI6IG1lc3NhZ2VzLAogICAgICAgIH0pCgogICAgd2hpbGUgVHJ1ZToKICAgICAgICBsaW5lID0gc3lzLnN0ZGluLnJlYWRsaW5lKCkKICAgICAgICBpZiBsaW5lID09ICIiOgogICAgICAgICAgICBicmVhawogICAgICAgIG1zZyA9IGxpbmUuc3RyaXAoKQogICAgICAgIGlmIG5vdCBtc2c6CiAgICAgICAgICAgIG91dC53cml0ZSgiPiAiKQogICAgICAgICAgICBvdXQuZmx1c2goKQogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIG1zZy5sb3dlcigpIGluICgiZXhpdCIsICJxdWl0IiwgIi9leGl0IiwgIi9xdWl0Iik6CiAgICAgICAgICAgIGJyZWFrCiAgICAgICAgX2xvdyA9IG1zZy5sb3dlcigpCiAgICAgICAgaWYgX2xvdyBpbiAoIi9zZXNzaW9ucyIsICIv66qp66GdIiwgIi9saXN0Iik6ICAjIFNFU1NJT05fUkVTVU1FX3YxCiAgICAgICAgICAgIF9zcyA9IF9saXN0X3Nlc3Npb25zKFNUQVRFX0RJUikKICAgICAgICAgICAgaWYgbm90IF9zczoKICAgICAgICAgICAgICAgIG91dC53cml0ZSgi7KCA7J6l65CcIOuMgO2ZlOqwgCDsl4bsirXri4jri6QuXG4+ICIpCiAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICBvdXQud3JpdGUoIuyggOyepeuQnCDrjIDtmZQgKOy1nOq3vOyInCk6XG4iKQogICAgICAgICAgICAgICAgZm9yIF9pLCBfcHAgaW4gZW51bWVyYXRlKF9zc1s6MjBdLCAxKToKICAgICAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgICAgIF9kID0gX2xvYWRfc2Vzc2lvbihfcHApIG9yIHt9CiAgICAgICAgICAgICAgICAgICAgICAgIF90ID0gX2QuZ2V0KCJ0aXRsZSIpIG9yIF9zZXNzaW9uX3ByZXZpZXcoX2QpIG9yICIo7KCc66qpIOyXhuydjCkiCiAgICAgICAgICAgICAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbjoKICAgICAgICAgICAgICAgICAgICAgICAgX3QgPSAiKOu2iOufrOyYpOq4sCDsi6TtjKgpIgogICAgICAgICAgICAgICAgICAgIG91dC53cml0ZSgiICBbJWRdICVzXG4iICUgKF9pLCBfdCkpCiAgICAgICAgICAgICAgICBvdXQud3JpdGUoIuydtOyWtO2VmOugpOuptDogL3Jlc3VtZSA867KI7Zi4PlxuPiAiKQogICAgICAgICAgICBvdXQuZmx1c2goKQogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIF9sb3cuc3RhcnRzd2l0aCgiL3Jlc3VtZSIpIG9yIF9sb3cuc3RhcnRzd2l0aCgiL+ydtOyWtCIpOiAgIyBTRVNTSU9OX1JFU1VNRV92MQogICAgICAgICAgICBfcGFydHMgPSBtc2cuc3BsaXQoTm9uZSwgMSkKICAgICAgICAgICAgX251bSA9IGludChfcGFydHNbMV0uc3RyaXAoKSkgaWYgKGxlbihfcGFydHMpID4gMSBhbmQgX3BhcnRzWzFdLnN0cmlwKCkuaXNkaWdpdCgpKSBlbHNlIDAKICAgICAgICAgICAgX3NzID0gX2xpc3Rfc2Vzc2lvbnMoU1RBVEVfRElSKQogICAgICAgICAgICBpZiAxIDw9IF9udW0gPD0gbGVuKF9zcyk6CiAgICAgICAgICAgICAgICB0cnk6CiAgICAgICAgICAgICAgICAgICAgX2QgPSBfbG9hZF9zZXNzaW9uKF9zc1tfbnVtIC0gMV0pIG9yIHt9CiAgICAgICAgICAgICAgICAgICAgX20gPSBfZC5nZXQoIm1lc3NhZ2VzIikgb3IgW10KICAgICAgICAgICAgICAgIGV4Y2VwdCBFeGNlcHRpb246CiAgICAgICAgICAgICAgICAgICAgX20gPSBbXQogICAgICAgICAgICAgICAgaWYgX206CiAgICAgICAgICAgICAgICAgICAgbWVzc2FnZXMgPSBfbQogICAgICAgICAgICAgICAgICAgIHNlc3Npb25fZmlsZSA9IF9zc1tfbnVtIC0gMV0KICAgICAgICAgICAgICAgICAgICBvdXQud3JpdGUoIlvrjIDtmZQg7J207Ja06rCA6riwIC0g7J207KCEIOuMgO2ZlOulvCDrtojrn6zsmZTsirXri4jri6RdXG4iKQogICAgICAgICAgICAgICAgICAgIGZvciBfbW0gaW4gbWVzc2FnZXM6CiAgICAgICAgICAgICAgICAgICAgICAgIF9yID0gX21tLmdldCgicm9sZSIpCiAgICAgICAgICAgICAgICAgICAgICAgIF9jb250ID0gX21tLmdldCgiY29udGVudCIsICIiKQogICAgICAgICAgICAgICAgICAgICAgICBpZiBfciA9PSAidXNlciI6CiAgICAgICAgICAgICAgICAgICAgICAgICAgICBvdXQud3JpdGUoIj4gIiArIF9jb250ICsgIlxuIikKICAgICAgICAgICAgICAgICAgICAgICAgZWxpZiBfciA9PSAiYXNzaXN0YW50IjoKICAgICAgICAgICAgICAgICAgICAgICAgICAgIG91dC53cml0ZShfY29udCArICJcbiIpCiAgICAgICAgICAgICAgICAgICAgb3V0LndyaXRlKCI+ICIpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgICAgIG91dC53cml0ZSgi67mIIOyEuOyFmOyeheuLiOuLpC5cbj4gIikKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAgICAgIG91dC53cml0ZSgi7IKs7Jqp67KVOiAvcmVzdW1lIDzrsojtmLg+ICAo66i87KCAIC9zZXNzaW9ucyDroZwg66qp66GdIO2ZleyduClcbj4gIikKICAgICAgICAgICAgb3V0LmZsdXNoKCkKICAgICAgICAgICAgY29udGludWUKICAgICAgICBpZiBfbG93IGluICgiL25ldyIsICIvY2xlYXIiLCAiL3Jlc2V0Iik6CiAgICAgICAgICAgIG1lc3NhZ2VzID0gW3sicm9sZSI6ICJzeXN0ZW0iLCAiY29udGVudCI6IF9zeXN9XQogICAgICAgICAgICBzZXNzaW9uX2NyZWF0ZWQgPSBfbm93X2lzbygpCiAgICAgICAgICAgIHNlc3Npb25fdGl0bGUgPSAiIgogICAgICAgICAgICBpZiBTVEFURV9ESVI6CiAgICAgICAgICAgICAgICBzZXNzaW9uX2ZpbGUgPSBvcy5wYXRoLmpvaW4oU1RBVEVfRElSLCAic2Vzc2lvbl8lcy5qc29uIiAlIF9uZXdfc2lkKCkpCiAgICAgICAgICAgIG91dC53cml0ZSgiW+q4sOyWtSDsgq3soJzrkKgg4oCUIOyDiCDrjIDtmZQg7Iuc7J6RXVxuPiAiKQogICAgICAgICAgICBvdXQuZmx1c2goKQogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGlmIF9sb3cuc3RhcnRzd2l0aCgiL3JlbmFtZSIpOgogICAgICAgICAgICBfbmV3bmFtZSA9IG1zZ1tsZW4oIi9yZW5hbWUiKTpdLnN0cmlwKCkKICAgICAgICAgICAgaWYgbm90IF9uZXduYW1lOgogICAgICAgICAgICAgICAgb3V0LndyaXRlKCLsgqzsmqnrspU6IC9yZW5hbWUgPOyDiCDsnbTrpoQ+XG4+ICIpCiAgICAgICAgICAgICAgICBvdXQuZmx1c2goKQogICAgICAgICAgICAgICAgY29udGludWUKICAgICAgICAgICAgc2Vzc2lvbl90aXRsZSA9IF9uZXduYW1lCiAgICAgICAgICAgIF9wZXJzaXN0KCkKICAgICAgICAgICAgb3V0LndyaXRlKCJb7J2066aEIOuzgOqyveuQqDogIiArIF9uZXduYW1lICsgIl1cbj4gIikKICAgICAgICAgICAgb3V0LmZsdXNoKCkKICAgICAgICAgICAgY29udGludWUKICAgICAgICAjIE1JRF9ET1dOR1JBREVfdjE6IOyXrOycoCDrtoDsobEg7IucIOuLpOydjCDthLTrtoDthLAg642UIOqwgOuyvOyatCDrqqjrjbjroZwgKOuQmOuPjOumrOyngCDslYrsnYwpCiAgICAgICAgaWYgX2RnX2xhZGRlcjoKICAgICAgICAgICAgX2ZyZWVfZGcgPSBfZGdfZnJlZV9nYigpCiAgICAgICAgICAgIGlmIF9mcmVlX2RnIGlzIG5vdCBOb25lOgogICAgICAgICAgICAgICAgX3VzYWJsZV9kZyA9IF9mcmVlX2RnICogX0RHX1NBRkVUWQogICAgICAgICAgICAgICAgX3RhcmdldF9kZyA9IGxlbihfZGdfbGFkZGVyKSAtIDEKICAgICAgICAgICAgICAgIGZvciBfaV9kZyBpbiByYW5nZShsZW4oX2RnX2xhZGRlcikpOgogICAgICAgICAgICAgICAgICAgIGlmIF9kZ19sYWRkZXJbX2lfZGddWzFdIDw9IF91c2FibGVfZGc6CiAgICAgICAgICAgICAgICAgICAgICAgIF90YXJnZXRfZGcgPSBfaV9kZwogICAgICAgICAgICAgICAgICAgICAgICBicmVhawogICAgICAgICAgICAgICAgaWYgX3RhcmdldF9kZyA+IF9kZ19pZHg6CiAgICAgICAgICAgICAgICAgICAgX29sZF9kZyA9IG1vZGVsCiAgICAgICAgICAgICAgICAgICAgX2RnX2lkeCA9IF90YXJnZXRfZGcKICAgICAgICAgICAgICAgICAgICBtb2RlbCA9IF9kZ19sYWRkZXJbX2RnX2lkeF1bMF0KICAgICAgICAgICAgICAgICAgICBpZiBtb2RlbCAhPSBfb2xkX2RnOgogICAgICAgICAgICAgICAgICAgICAgICBvdXQud3JpdGUoIlvrqqjrjbgg7J6Q64+ZIOqwleuTsV0gJXMgLT4gJXMgKOyXrOycoCAlLjFmR0IpXG4iCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAlIChfb2xkX2RnLCBtb2RlbCwgX2ZyZWVfZGcpKQogICAgICAgICAgICAgICAgICAgICAgICBvdXQuZmx1c2goKQogICAgICAgIHRyeToKICAgICAgICAgICAgaGFuZGxlX3R1cm4obXNnLCBtZXNzYWdlcywgYXJncy5hcGlfYmFzZSwgbW9kZWwsCiAgICAgICAgICAgICAgICAgICAgICAgIG51bV9jdHgsIG51bV9wcmVkaWN0LCBXT1JLU1BBQ0UsIG91dCkKICAgICAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6CiAgICAgICAgICAgIG91dC53cml0ZSgiXG5b7Jik66WYXSDthLQg7LKY66asIOyLpO2MqDogIiArIHJlcHIoZSkgKyAiXG4iKQogICAgICAgICAgICB0cmFjZWJhY2sucHJpbnRfZXhjKGZpbGU9b3V0KQogICAgICAgIF9wZXJzaXN0KCkKICAgICAgICBvdXQud3JpdGUoIlxuPiAiKQogICAgICAgIG91dC5mbHVzaCgpCiAgICByZXR1cm4gMAoKCmlmIF9fbmFtZV9fID09ICJfX21haW5fXyI6CiAgICBzeXMuZXhpdChtYWluKCkpCg=="
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
        # NETMODE_WARP_v4: NET_MODE 인지 프록시 (warp=SOCKS 전용, tor=http+socks)
        try:
            from .. import config as _cfgN
            _penv = _cfgN.net_proxy_env()
        except Exception:
            _penv = {
                "HTTP_PROXY": "socks5h://llm_warp:1080",
                "HTTPS_PROXY": "socks5h://llm_warp:1080",
                "http_proxy": "socks5h://llm_warp:1080",
                "https_proxy": "socks5h://llm_warp:1080",
                "ALL_PROXY": "socks5h://llm_warp:1080",
                "all_proxy": "socks5h://llm_warp:1080",
                "NO_PROXY": "host.docker.internal,localhost,127.0.0.1",
                "no_proxy": "host.docker.internal,localhost,127.0.0.1",
            }
        for _pk, _pv in _penv.items():
            cmd += ["-e", _pk + "=" + _pv]
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
