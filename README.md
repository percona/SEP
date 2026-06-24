# Repository Coverage



| Name                                                                                                            |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|---------------------------------------------------------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| app/api/deps.py                                                                                                 |       48 |        0 |        8 |        0 |    100% |           |
| app/api/main.py                                                                                                 |        6 |        0 |        0 |        0 |    100% |           |
| app/api/routes/config.py                                                                                        |        9 |        0 |        0 |        0 |    100% |           |
| app/api/routes/oauth.py                                                                                         |       60 |        0 |       10 |        0 |    100% |           |
| app/api/routes/users.py                                                                                         |       21 |        0 |        4 |        0 |    100% |           |
| app/celery.py                                                                                                   |       32 |        4 |        2 |        0 |     88% | 45, 51-53 |
| app/core/alerts/config.py                                                                                       |       42 |        0 |        4 |        0 |    100% |           |
| app/core/alerts/models.py                                                                                       |       57 |        0 |       10 |        0 |    100% |           |
| app/core/alerts/providers/pagerduty.py                                                                          |       35 |        1 |        0 |        0 |     97% |       110 |
| app/core/auth/exceptions.py                                                                                     |       11 |        0 |        0 |        0 |    100% |           |
| app/core/auth/models.py                                                                                         |       63 |        1 |        0 |        0 |     98% |       170 |
| app/core/auth/providers/casdoor.py                                                                              |      123 |       61 |       26 |        3 |     44% |53, 126-127, 139, 168-\>170, 187, 218-219, 241-248, 276-296, 304-305, 326-335, 351-352, 372-391, 409-414, 424-425, 439, 451-455, 467-471 |
| app/core/auth/utils.py                                                                                          |        5 |        0 |        0 |        0 |    100% |           |
| app/core/celery/config.py                                                                                       |       23 |        0 |        2 |        1 |     96% |   70-\>72 |
| app/core/celery/crud.py                                                                                         |       26 |        2 |        4 |        1 |     90% |     91-97 |
| app/core/celery/db.py                                                                                           |        8 |        0 |        0 |        0 |    100% |           |
| app/core/celery/deps.py                                                                                         |       10 |        0 |        0 |        0 |    100% |           |
| app/core/celery/models.py                                                                                       |       36 |        2 |        6 |        2 |     90% |   72, 135 |
| app/core/celery/utils.py                                                                                        |       31 |        2 |       10 |        2 |     90% |   92, 120 |
| app/core/config.py                                                                                              |      210 |        7 |       44 |        5 |     95% |201-\>exit, 402, 436, 520, 524, 600, 613, 649-\>651, 654 |
| app/core/db/config.py                                                                                           |       17 |        0 |        2 |        0 |    100% |           |
| app/core/db/crud.py                                                                                             |      285 |       22 |       82 |        9 |     90% |194, 246-\>248, 248-\>250, 250-\>252, 259-\>275, 310-327, 345, 350, 367, 481-484, 850-854, 1118-1119 |
| app/core/db/models.py                                                                                           |       14 |        0 |        0 |        0 |    100% |           |
| app/core/db/sql\_types.py                                                                                       |       37 |        0 |       12 |        0 |    100% |           |
| app/core/db/utils.py                                                                                            |       54 |        4 |       22 |        4 |     89% |76, 191, 220, 223 |
| app/core/exceptions.py                                                                                          |       32 |        0 |        0 |        0 |    100% |           |
| app/core/log.py                                                                                                 |       21 |        0 |        8 |        0 |    100% |           |
| app/core/middleware/log\_context.py                                                                             |       26 |        0 |        2 |        0 |    100% |           |
| app/core/middleware/security\_headers.py                                                                        |      105 |        0 |       20 |        1 |     99% |221-\>exit |
| app/core/models.py                                                                                              |       20 |        0 |        2 |        0 |    100% |           |
| app/core/pagination/deps.py                                                                                     |       17 |        0 |        2 |        0 |    100% |           |
| app/core/pagination/models.py                                                                                   |       75 |        0 |       20 |        0 |    100% |           |
| app/core/pmm.py                                                                                                 |       51 |        1 |       10 |        1 |     97% |        53 |
| app/core/requests/registry.py                                                                                   |       64 |        5 |       22 |        5 |     88% |101, 112, 152, 163, 173 |
| app/core/requests/remote\_api.py                                                                                |      215 |        8 |       46 |        5 |     95% |96, 115, 414, 454-457, 465, 472-\>471 |
| app/core/security.py                                                                                            |        4 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/api/export.py                                                                       |       10 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/api/models.py                                                                       |       13 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/api/routes.py                                                                       |      238 |       27 |       74 |        7 |     88% |277, 378, 401, 531-538, 561-568, 577-586, 726-733, 763-764, 819, 821-822, 890, 892, 915, 1045-\>1062, 1049-1061 |
| app/core/settings\_override/cache.py                                                                            |      118 |       13 |       46 |        6 |     86% |192-197, 210-215, 297, 360, 401, 405-412 |
| app/core/settings\_override/lifecycle.py                                                                        |       69 |        1 |       14 |        0 |     99% |       267 |
| app/core/settings\_override/manager.py                                                                          |        5 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/models.py                                                                           |       22 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/proxy.py                                                                            |       22 |        0 |        2 |        0 |    100% |           |
| app/core/settings\_override/registry.py                                                                         |      296 |       11 |      130 |       10 |     95% |613, 792, 824, 856, 988, 995, 1013-\>1017, 1018-1020, 1035, 1115 |
| app/core/utils/async\_run.py                                                                                    |       13 |        0 |        0 |        0 |    100% |           |
| app/core/utils/cache.py                                                                                         |       92 |        7 |       18 |        4 |     88% |60-62, 147-\>153, 151, 186-\>191, 208-209, 223 |
| app/core/utils/date\_time.py                                                                                    |        8 |        0 |        2 |        0 |    100% |           |
| app/core/utils/dict.py                                                                                          |       27 |        4 |       10 |        0 |     84% |   160-163 |
| app/core/utils/fields.py                                                                                        |      201 |        8 |       26 |        6 |     94% |168, 234-235, 402, 406, 522, 570, 593 |
| app/core/utils/imports.py                                                                                       |       28 |        0 |        8 |        0 |    100% |           |
| app/core/utils/iterators.py                                                                                     |       18 |        0 |        6 |        0 |    100% |           |
| app/core/utils/lazy.py                                                                                          |       31 |        0 |        4 |        0 |    100% |           |
| app/core/utils/openapi.py                                                                                       |      129 |        6 |       82 |        8 |     91% |73-\>75, 78-79, 155, 157-\>156, 162-163, 206-\>208, 225-\>224, 242 |
| app/core/utils/path.py                                                                                          |        8 |        0 |        0 |        0 |    100% |           |
| app/core/utils/pydantic.py                                                                                      |       59 |        0 |       20 |        0 |    100% |           |
| app/core/utils/serialization.py                                                                                 |        7 |        0 |        0 |        0 |    100% |           |
| app/core/utils/strings.py                                                                                       |       24 |        3 |        4 |        1 |     79% |     64-69 |
| app/inventory/config.py                                                                                         |       11 |        0 |        0 |        0 |    100% |           |
| app/inventory/constants.py                                                                                      |        2 |        0 |        0 |        0 |    100% |           |
| app/inventory/crud.py                                                                                           |       24 |        0 |        0 |        0 |    100% |           |
| app/inventory/db.py                                                                                             |        7 |        1 |        0 |        0 |     86% |        40 |
| app/inventory/deps.py                                                                                           |       24 |        3 |        0 |        0 |     88% |     38-40 |
| app/inventory/main.py                                                                                           |       28 |        6 |        2 |        1 |     77% |42, 73-74, 78-82 |
| app/inventory/models.py                                                                                         |       92 |        0 |        4 |        0 |    100% |           |
| app/inventory/routes/nodes.py                                                                                   |       52 |        2 |        4 |        0 |     93% |  133, 135 |
| app/inventory/routes/schemas.py                                                                                 |       38 |        0 |        2 |        0 |    100% |           |
| app/inventory/routes/services.py                                                                                |       52 |        3 |        6 |        0 |     88% |125, 127, 169 |
| app/inventory/routes/tables.py                                                                                  |       26 |        0 |        0 |        0 |    100% |           |
| app/main.py                                                                                                     |       78 |       27 |        4 |        1 |     63% |185-188, 193-197, 201-255 |
| app/models.py                                                                                                   |       74 |        4 |       10 |        0 |     90% |   208-213 |
| app/sep/api/constants.py                                                                                        |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/api/host\_resolution.py                                                                                 |        9 |        0 |        4 |        0 |    100% |           |
| app/sep/api/models.py                                                                                           |       15 |        0 |        2 |        0 |    100% |           |
| app/sep/api/openapi.py                                                                                          |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/api/router.py                                                                                           |       32 |        0 |        4 |        0 |    100% |           |
| app/sep/api/routes/app\_state.py                                                                                |       44 |       12 |       10 |        2 |     59% |179, 185, 187-194, 201, 207-208, 236-237, 242-243, 250 |
| app/sep/api/routes/apps.py                                                                                      |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/dashboard.py                                                                                 |       35 |        0 |        6 |        0 |    100% |           |
| app/sep/api/routes/hosts.py                                                                                     |       22 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/schemas.py                                                                                   |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/services.py                                                                                  |       17 |        0 |        2 |        0 |    100% |           |
| app/sep/api/routes/settings.py                                                                                  |      108 |        7 |       48 |        6 |     90% |95, 100, 278-280, 282-\>304, 290, 296, 300-\>302 |
| app/sep/api/routes/task\_history.py                                                                             |       13 |        0 |        2 |        0 |    100% |           |
| app/sep/api/routes/task\_stats.py                                                                               |       13 |        0 |        0 |        0 |    100% |           |
| app/sep/api/task\_history\_merge.py                                                                             |       55 |        4 |       16 |        3 |     90% |57, 61-62, 113, 115-\>117 |
| app/sep/app\_drain.py                                                                                           |       83 |        2 |       14 |        2 |     96% |135-\>137, 204, 210 |
| app/sep/artifact\_constants.py                                                                                  |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/celery.py                                                                                               |      143 |       19 |       46 |        6 |     86% |56-\>52, 74-\>52, 115, 161, 199-200, 221-223, 226, 232-245, 252 |
| app/sep/clients/pmm.py                                                                                          |      247 |        3 |       66 |        2 |     98% |218, 485, 487 |
| app/sep/config.py                                                                                               |      237 |       11 |       46 |       11 |     92% |137, 186, 337, 414, 431, 445, 449, 451, 453, 496, 614 |
| app/sep/connectivity.py                                                                                         |       77 |        1 |       16 |        1 |     98% |       103 |
| app/sep/crud.py                                                                                                 |       81 |        0 |       10 |        0 |    100% |           |
| app/sep/db/engine.py                                                                                            |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/db/seed.py                                                                                              |       50 |       15 |       24 |        3 |     59% |66-\>82, 82-\>115, 84-98 |
| app/sep/deps.py                                                                                                 |      325 |       10 |       60 |        2 |     96% |380, 383-384, 402, 991-992, 1174-1177 |
| app/sep/exceptions.py                                                                                           |       13 |        0 |        0 |        0 |    100% |           |
| app/sep/inventory.py                                                                                            |       97 |        8 |       10 |        2 |     91% |81, 92, 229, 286, 306-\>308, 326, 363, 385, 419 |
| app/sep/main.py                                                                                                 |      207 |       17 |       36 |        5 |     90% |93-95, 137-139, 271-288, 345-\>350, 371, 454-\>456, 569-\>573, 614-618 |
| app/sep/middleware/csrf.py                                                                                      |       48 |        0 |       14 |        0 |    100% |           |
| app/sep/middleware/messages/\_middleware.py                                                                     |       28 |        0 |        6 |        0 |    100% |           |
| app/sep/middleware/messages/\_utils.py                                                                          |       54 |        1 |       14 |        4 |     93% |119, 262-\>261, 264-\>266, 266-\>268 |
| app/sep/middleware/messages/config.py                                                                           |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/middleware/messages/models.py                                                                           |       31 |        0 |        4 |        0 |    100% |           |
| app/sep/migrations/\_discovery.py                                                                               |       33 |        2 |       12 |        3 |     89% |70, 103, 109-\>112 |
| app/sep/migrations/env.py                                                                                       |       39 |        5 |        4 |        2 |     84% |39-\>42, 68-79, 121 |
| app/sep/migrations/versions/2024\_10\_07\_1450-7f4dec8bc76a\_create\_sync\_tables.py                            |       26 |        8 |        0 |        0 |     69% |     69-76 |
| app/sep/migrations/versions/2024\_10\_08\_2047-eeac2926bbea\_remove\_task\_history\_id\_field.py                |       12 |        1 |        0 |        0 |     92% |        45 |
| app/sep/migrations/versions/2025\_08\_08\_1005-9307f0f5ee54\_create\_snippet\_table.py                          |       16 |        3 |        0 |        0 |     81% |     59-61 |
| app/sep/migrations/versions/2026\_03\_02\_1612-810c31754b54\_add\_index\_for\_syncinstance\_syncer.py           |       12 |        1 |        0 |        0 |     92% |        45 |
| app/sep/migrations/versions/2026\_05\_18\_2014-ed97b99eef38\_add\_setting\_override\_table.py                   |       18 |        4 |        0 |        0 |     78% |     81-86 |
| app/sep/migrations/versions/2026\_06\_01\_1530-e5c224619161\_add\_appstate\_table.py                            |       14 |        2 |        0 |        0 |     86% |     53-54 |
| app/sep/migrations/versions/2026\_06\_02\_1512-378c0872642f\_extend\_setting\_class\_enum\_settings\_alert.py   |       13 |        3 |        0 |        0 |     77% |     68-73 |
| app/sep/migrations/versions/2026\_06\_15\_1725-64f10ead74f6\_add\_seppluginperiodictask.py                      |       16 |        3 |        0 |        0 |     81% |     55-57 |
| app/sep/migrations/versions/2026\_06\_16\_1200-a7c4e9f1b2d3\_add\_lifecycle\_state\_to\_app\_state.py           |       26 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_16\_1600-b8d5f2a9c1e4\_add\_apprunningtask\_table.py                      |       16 |        3 |        0 |        0 |     81% |     54-56 |
| app/sep/migrations/versions/2026\_06\_22\_1223-410eedfc5b43\_merge\_heads.py                                    |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_22\_1400-c97e7e47c935\_extend\_setting\_class\_enum\_anonymizer.py        |       13 |        3 |        0 |        0 |     77% |     71-75 |
| app/sep/models.py                                                                                               |       66 |        1 |        2 |        1 |     97% |       247 |
| app/sep/periodic\_tasks.py                                                                                      |       41 |        0 |       12 |        0 |    100% |           |
| app/sep/plugins/alert\_troubleshooting/api\_routes.py                                                           |       23 |        4 |        2 |        0 |     76% |64-65, 73-80 |
| app/sep/plugins/alert\_troubleshooting/deps.py                                                                  |      135 |       18 |       46 |        3 |     87% |122, 124-\>126, 237, 259-261, 280, 364, 388-394, 418-420, 444-447, 474 |
| app/sep/plugins/alert\_troubleshooting/models.py                                                                |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/alert\_troubleshooting/routes.py                                                                |       67 |        5 |       14 |        2 |     91% |60-\>56, 68-\>56, 143-148, 199-200 |
| app/sep/plugins/alert\_troubleshooting/schema.py                                                                |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/alerts/api\_routes.py                                                                           |      121 |       16 |       16 |        0 |     85% |179, 195-198, 242-252 |
| app/sep/plugins/alerts/app.py                                                                                   |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/alerts/config.py                                                                                |       19 |        0 |        2 |        0 |    100% |           |
| app/sep/plugins/alerts/crud.py                                                                                  |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/alerts/deps.py                                                                                  |       91 |        0 |       20 |        0 |    100% |           |
| app/sep/plugins/alerts/loader.py                                                                                |       22 |        0 |        6 |        0 |    100% |           |
| app/sep/plugins/alerts/migrations/versions/2026\_04\_20\_1817-d21ad387df7a\_create\_alert\_backup\_table.py     |       14 |        0 |        2 |        0 |    100% |           |
| app/sep/plugins/alerts/models.py                                                                                |       22 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/alerts/restore.py                                                                               |      102 |        3 |       32 |        3 |     96% |95, 100, 169 |
| app/sep/plugins/alerts/routes.py                                                                                |      111 |       12 |       16 |        1 |     90% |97-99, 280-281, 321-339 |
| app/sep/plugins/alerts/schemas.py                                                                               |       25 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/alters/api\_routes.py                                                                           |       58 |        8 |        4 |        1 |     85% |80, 97, 142-147, 189-192, 199-204 |
| app/sep/plugins/alters/deps.py                                                                                  |      304 |        9 |      116 |       10 |     95% |328-\>340, 334-\>333, 338-\>333, 565-\>550, 626, 701-702, 804, 827-828, 980, 991, 993, 1025-\>1029 |
| app/sep/plugins/alters/models.py                                                                                |      114 |        2 |       12 |        2 |     97% |   57, 261 |
| app/sep/plugins/alters/pre\_checks.py                                                                           |      236 |      236 |       72 |        0 |      0% |    27-638 |
| app/sep/plugins/alters/routes.py                                                                                |      105 |        2 |        8 |        1 |     97% |   303-306 |
| app/sep/plugins/alters/schema.py                                                                                |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/archives/alerts.py                                                                              |      130 |        6 |       40 |        4 |     94% |178, 213, 255, 338-339, 349, 371-\>376 |
| app/sep/plugins/archives/api\_routes.py                                                                         |       31 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/archives/constants.py                                                                           |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/archives/deps.py                                                                                |      106 |        1 |       36 |        2 |     98% |98-\>100, 420-\>430, 456 |
| app/sep/plugins/archives/models.py                                                                              |       75 |        0 |        2 |        0 |    100% |           |
| app/sep/plugins/archives/payload                                                                                |      195 |      135 |       60 |        2 |     28% |44-235, 240-246, 295, 300-309, 385-400, 405-409, 413 |
| app/sep/plugins/archives/routes.py                                                                              |       91 |        3 |       16 |        5 |     93% |136-\>138, 143, 145, 147, 150-\>152 |
| app/sep/plugins/archives/schema.py                                                                              |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/atw/api\_routes.py                                                                              |       42 |        0 |       14 |        1 |     98% | 111-\>121 |
| app/sep/plugins/atw/app.py                                                                                      |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/atw/models.py                                                                                   |       34 |        0 |        2 |        0 |    100% |           |
| app/sep/plugins/atw/schema.py                                                                                   |       13 |        0 |        2 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/api\_routes.py                                                                    |       43 |        0 |        2 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/app.py                                                                            |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/deps.py                                                                           |      116 |       22 |       20 |        2 |     76% |133, 304-323, 333-334, 409, 428-430, 463 |
| app/sep/plugins/backup\_mongo/models.py                                                                         |      151 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/api\_routes.py                                                            |       37 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/deps.py                                                                   |      196 |       41 |       46 |        5 |     73% |110, 153-174, 204, 264-265, 303, 538-552, 566-567, 636, 758-769, 804 |
| app/sep/plugins/backup\_mongo/restore/models.py                                                                 |      154 |        7 |       20 |        5 |     93% |62-64, 66, 69-73, 271-\>275, 297-\>299, 563 |
| app/sep/plugins/backup\_mongo/restore/routes.py                                                                 |      140 |       36 |       18 |        9 |     72% |71-72, 80-81, 106-111, 121-126, 143-144, 147-152, 173, 196, 214, 245-246, 252, 289-290, 295-296, 321-322, 352-361, 400-402 |
| app/sep/plugins/backup\_mongo/restore/schema.py                                                                 |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/spec.py                                                                   |       34 |        0 |        2 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/views.py                                                                  |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/routes.py                                                                         |       83 |       35 |        2 |        0 |     56% |66, 147-208, 229-238, 252-255 |
| app/sep/plugins/backup\_mongo/schema.py                                                                         |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/spec.py                                                                           |       64 |       17 |       26 |        7 |     67% |84-\>87, 99-112, 140-142, 144-\>147, 148, 151, 156, 158-\>163 |
| app/sep/plugins/backup\_mongo/views.py                                                                          |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/app.py                                                                               |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/deps.py                                                                              |       90 |        7 |       22 |        1 |     93% |121-122, 125, 159-161, 275 |
| app/sep/plugins/backup\_pg/models.py                                                                            |       63 |        1 |        2 |        1 |     97% |       230 |
| app/sep/plugins/backup\_pg/routes.py                                                                            |       62 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/spec.py                                                                              |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/views.py                                                                             |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/checksums/app.py                                                                                |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/checksums/deps.py                                                                               |      107 |       54 |       40 |        3 |     42% |72-73, 75-76, 96-134, 345-347, 364-369, 385-412, 425-452, 463, 493 |
| app/sep/plugins/checksums/models.py                                                                             |       38 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/checksums/routes.py                                                                             |       65 |       29 |        0 |        0 |     55% |60-61, 108-162, 182-190, 227-228 |
| app/sep/plugins/checksums/spec.py                                                                               |       26 |        0 |        8 |        1 |     97% |   82-\>84 |
| app/sep/plugins/checksums/views.py                                                                              |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/dipper/api\_routes.py                                                                           |       64 |        4 |        4 |        1 |     93% |79-80, 135-136 |
| app/sep/plugins/dipper/constants.py                                                                             |       10 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/dipper/deps.py                                                                                  |      185 |       40 |       52 |        9 |     76% |128-130, 151-152, 175-180, 194-195, 246-275, 310-\>316, 338-341, 342-\>349, 372, 373-\>375, 483, 485, 487, 575, 614 |
| app/sep/plugins/dipper/models.py                                                                                |       14 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/dipper/payloads/pcs-collect-pmm-mysql.py                                                        |      303 |      259 |      122 |        3 |     11% |   266-880 |
| app/sep/plugins/dipper/payloads/pcs-collect-pmm-valkey.py                                                       |      225 |      192 |       82 |        0 |     11% |   155-658 |
| app/sep/plugins/dipper/routes.py                                                                                |       67 |       41 |       12 |        1 |     34% |94-199, 216-221 |
| app/sep/plugins/dipper/schema.py                                                                                |       38 |        1 |       10 |        1 |     96% |       236 |
| app/sep/plugins/framework/api.py                                                                                |      265 |       10 |       98 |        7 |     95% |125-\>123, 180-185, 680-681, 701, 806, 812, 817, 823, 838 |
| app/sep/plugins/framework/apps.py                                                                               |      224 |        8 |       86 |        8 |     95% |468, 484, 502, 539, 544, 550, 555, 562 |
| app/sep/plugins/framework/base.py                                                                               |       27 |        2 |        6 |        2 |     88% |    89, 96 |
| app/sep/plugins/framework/cascade.py                                                                            |      183 |        0 |       58 |        1 |     99% | 123-\>125 |
| app/sep/plugins/framework/conformance.py                                                                        |       85 |        8 |       40 |        6 |     87% |67, 157, 193-197, 256, 269, 273 |
| app/sep/plugins/framework/connectivity.py                                                                       |       24 |        0 |        6 |        0 |    100% |           |
| app/sep/plugins/framework/deprecation.py                                                                        |       19 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/framework/deps.py                                                                               |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/framework/form\_dsl/conformance.py                                                              |       46 |        9 |       18 |        3 |     75% |65, 69, 85-93 |
| app/sep/plugins/framework/form\_dsl/derivation.py                                                               |      289 |       25 |      138 |       23 |     87% |211, 228, 325, 341, 346, 347-\>343, 356, 366-\>372, 369-371, 384-386, 390, 392-\>387, 394, 411, 417, 432, 435, 443, 449-450, 452, 497, 503, 640 |
| app/sep/plugins/framework/form\_dsl/markers.py                                                                  |       80 |        0 |        2 |        0 |    100% |           |
| app/sep/plugins/framework/form\_dsl/model.py                                                                    |       14 |        1 |        2 |        1 |     88% |        68 |
| app/sep/plugins/framework/registry.py                                                                           |       53 |        1 |       20 |        1 |     97% |       156 |
| app/sep/plugins/framework/responses.py                                                                          |       68 |        0 |       10 |        0 |    100% |           |
| app/sep/plugins/framework/rules.py                                                                              |      535 |        7 |      130 |        5 |     98% |322, 327, 332, 544, 860, 1347, 1367 |
| app/sep/plugins/framework/schema.py                                                                             |      339 |        2 |      106 |        2 |     99% |1041, 1437 |
| app/sep/plugins/framework/script\_source.py                                                                     |       35 |        0 |        4 |        0 |    100% |           |
| app/sep/plugins/framework/spec.py                                                                               |      117 |        1 |       44 |        1 |     99% |       366 |
| app/sep/plugins/framework/task\_status.py                                                                       |       29 |        0 |       10 |        0 |    100% |           |
| app/sep/plugins/inventory/api\_routes.py                                                                        |       64 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/inventory/app.py                                                                                |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/inventory/deps.py                                                                               |      140 |       13 |       54 |        3 |     90% |275-299, 411-416, 459, 466 |
| app/sep/plugins/inventory/models.py                                                                             |       29 |        1 |        8 |        1 |     95% |        93 |
| app/sep/plugins/inventory/routes.py                                                                             |      173 |        0 |       16 |        0 |    100% |           |
| app/sep/plugins/inventory/schema.py                                                                             |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/inventory/sync.py                                                                               |       40 |        0 |       16 |        0 |    100% |           |
| app/sep/plugins/mysql\_backups/app.py                                                                           |       10 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/mysql\_backups/deps.py                                                                          |       84 |        5 |       24 |        3 |     93% |102, 164, 167-168, 185-\>188, 248 |
| app/sep/plugins/mysql\_backups/models.py                                                                        |      200 |        5 |       14 |        3 |     95% |544-546, 579, 594 |
| app/sep/plugins/mysql\_backups/restore/app.py                                                                   |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/mysql\_backups/restore/deps.py                                                                  |       89 |       14 |       18 |        4 |     83% |72-\>76, 104, 161-162, 166, 171, 174-175, 258, 274-279, 312 |
| app/sep/plugins/mysql\_backups/restore/models.py                                                                |      127 |        1 |        6 |        1 |     98% |        52 |
| app/sep/plugins/mysql\_backups/restore/routes.py                                                                |       66 |        8 |        0 |        0 |     88% |147-148, 177-186, 223-225 |
| app/sep/plugins/mysql\_backups/restore/spec.py                                                                  |       37 |        1 |       10 |        1 |     96% |       101 |
| app/sep/plugins/mysql\_backups/restore/views.py                                                                 |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/mysql\_backups/routes.py                                                                        |       75 |        6 |        0 |        0 |     92% |74, 182-183, 236-241 |
| app/sep/plugins/mysql\_backups/spec.py                                                                          |       25 |        0 |        8 |        0 |    100% |           |
| app/sep/plugins/mysql\_backups/views.py                                                                         |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/report/api\_routes.py                                                                           |       33 |        0 |        2 |        0 |    100% |           |
| app/sep/plugins/report/app.py                                                                                   |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/report/deps.py                                                                                  |       28 |        0 |        6 |        1 |     97% | 75-\>exit |
| app/sep/plugins/report/models.py                                                                                |      111 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/report/routes.py                                                                                |       39 |        0 |        2 |        0 |    100% |           |
| app/sep/plugins/report/schemas.py                                                                               |        6 |        6 |        0 |        0 |      0% |     18-43 |
| app/sep/plugins/report/service.py                                                                               |      378 |       16 |      132 |       14 |     94% |126, 130, 331, 345-346, 407, 444-445, 447, 451, 452-\>455, 553, 558, 560-\>550, 566, 575, 638, 645 |
| app/sep/plugins/snippets/app.py                                                                                 |       10 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/snippets/deps.py                                                                                |      145 |       16 |       44 |        8 |     85% |69, 140-142, 161-\>169, 179, 209, 240, 271, 336-344, 431, 505, 537-544 |
| app/sep/plugins/snippets/extra\_routes.py                                                                       |       66 |        5 |       10 |        0 |     93% |78-80, 167, 198 |
| app/sep/plugins/snippets/models.py                                                                              |       27 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/snippets/routes.py                                                                              |      100 |       44 |       14 |        0 |     51% |81-83, 112, 122, 135-138, 172-182, 186-188, 199-222, 267-306 |
| app/sep/plugins/snippets/schema.py                                                                              |       79 |        4 |       22 |        1 |     95% |150-152, 301 |
| app/sep/plugins/snippets/script\_source.py                                                                      |       71 |        1 |       14 |        1 |     98% |       237 |
| app/sep/plugins/tasks/api\_routes.py                                                                            |       25 |        0 |        2 |        0 |    100% |           |
| app/sep/plugins/tasks/deps.py                                                                                   |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/plugins/tasks/models.py                                                                                 |       30 |        1 |        2 |        1 |     94% |       138 |
| app/sep/plugins/tasks/routes.py                                                                                 |       56 |        0 |        2 |        1 |     98% | 107-\>115 |
| app/sep/plugins/tasks/schema.py                                                                                 |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/routes/artifacts.py                                                                                     |       29 |        1 |        8 |        1 |     95% |        67 |
| app/sep/routes/download\_files.py                                                                               |       43 |        0 |        8 |        1 |     98% |   81-\>87 |
| app/sep/routes/execution\_events.py                                                                             |       14 |        0 |        2 |        0 |    100% |           |
| app/sep/routes/inventory\_ajax.py                                                                               |       24 |        0 |        0 |        0 |    100% |           |
| app/sep/routes/periodic\_tasks.py                                                                               |       31 |        1 |        4 |        2 |     91% |79-\>88, 83 |
| app/sep/routes/stop\_task.py                                                                                    |       19 |        0 |        2 |        0 |    100% |           |
| app/sep/routes/stream\_logs.py                                                                                  |       78 |       17 |       12 |        3 |     78% |86, 91-98, 110-115, 117-120, 127-132, 181-\>176, 186-191, 193-197, 202-207 |
| app/sep/snippets/config.py                                                                                      |      130 |       20 |       20 |        7 |     79% |124, 196-205, 217, 267, 349-354, 428-\>447, 435, 446, 462-465 |
| app/sep/snippets/crud.py                                                                                        |       15 |        0 |        2 |        0 |    100% |           |
| app/sep/snippets/forms.py                                                                                       |      248 |       10 |       46 |       10 |     92% |181, 518-\>520, 672-675, 863-\>870, 865-\>870, 867, 869, 880, 988, 995, 996-\>1004 |
| app/sep/snippets/models/meta.py                                                                                 |      181 |        1 |       58 |        3 |     98% |406, 585-\>587, 587-\>589 |
| app/sep/snippets/models/snippet.py                                                                              |      376 |       15 |       90 |        4 |     95% |253-\>276, 277-278, 631-643, 724-726, 846-848, 931 |
| app/sep/snippets/utils.py                                                                                       |       32 |        0 |       10 |        0 |    100% |           |
| app/sep/sync/exceptions.py                                                                                      |       25 |        0 |        0 |        0 |    100% |           |
| app/sep/sync/models.py                                                                                          |      368 |       42 |      100 |       20 |     85% |81-90, 102-\>104, 104-\>106, 125, 131-\>133, 134-\>136, 195-\>201, 273-275, 304-\>302, 336, 396-397, 544, 592, 698-\>exit, 716, 730, 750-751, 786-\>exit, 831, 845, 867-868, 904-\>exit, 949, 962, 986-988, 1021-\>exit, 1130-\>exit, 1169, 1313-1315, 1422-1424, 1429-1435, 1439 |
| app/sep/sync/syncers/mysql/payload.py                                                                           |      175 |       47 |       54 |        5 |     69% |156-\>164, 240-244, 249-254, 267-273, 277-300, 354-\>370, 373, 394-402, 421 |
| app/sep/sync/syncers/mysql/syncer.py                                                                            |      222 |        1 |       86 |        7 |     97% |112, 268-\>270, 272-\>274, 586-\>594, 595-\>599, 676-\>687, 762-\>766 |
| app/sep/sync/syncers/pmm.py                                                                                     |       93 |       20 |       30 |        7 |     72% |83-87, 107-110, 121, 176-184, 231-\>233, 233-\>229, 236-252, 291-294, 344 |
| app/sep/sync/syncers/system\_facts/payload.py                                                                   |      235 |       19 |       78 |       12 |     90% |52-\>58, 147-148, 176, 222-224, 231, 233-\>229, 244-251, 261-\>263, 263-\>265, 265-\>267, 282-284, 290-292, 316, 415-\>417, 417-\>419, 522, 533 |
| app/sep/sync/syncers/system\_facts/syncer.py                                                                    |      118 |        7 |       28 |        3 |     93% |104, 169-170, 245, 256-\>254, 310-311, 350 |
| app/sep/tasks.py                                                                                                |       31 |        0 |       12 |        1 |     98% |   69-\>84 |
| app/sep/utils/decorators.py                                                                                     |       10 |        0 |        0 |        0 |    100% |           |
| app/sep/utils/forms.py                                                                                          |       20 |        0 |        6 |        0 |    100% |           |
| app/sep/utils/jinja.py                                                                                          |       61 |       10 |       10 |        1 |     79% |105, 124, 135-140, 171-172 |
| app/sep/utils/static.py                                                                                         |       10 |        0 |        2 |        0 |    100% |           |
| app/tasks/alert\_hooks.py                                                                                       |       31 |        0 |        4 |        0 |    100% |           |
| app/tasks/anonymizer/anonymize.py                                                                               |       50 |        0 |       18 |        3 |     96% |57-\>62, 77-\>82, 96-\>98 |
| app/tasks/anonymizer/config.py                                                                                  |       30 |        1 |        6 |        1 |     94% |        78 |
| app/tasks/anonymizer/entities.py                                                                                |       28 |        0 |        2 |        0 |    100% |           |
| app/tasks/celery.py                                                                                             |      316 |       11 |       76 |        6 |     96% |243-\>255, 252-\>254, 362-\>364, 379, 389-391, 413-415, 722, 793, 816-817, 918-\>933 |
| app/tasks/config.py                                                                                             |       26 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/constants.py                                                                             |        4 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/models.py                                                                                |       11 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/payload.py                                                                               |       68 |        1 |        8 |        1 |     97% |       162 |
| app/tasks/connectivity/routes.py                                                                                |       16 |        0 |        2 |        0 |    100% |           |
| app/tasks/connectivity/service.py                                                                               |      103 |        2 |       32 |        5 |     95% |178, 330-\>329, 348, 353-\>352, 363-\>362 |
| app/tasks/crud.py                                                                                               |      214 |        1 |       56 |        2 |     99% |369-\>371, 446 |
| app/tasks/db/engine.py                                                                                          |        8 |        0 |        0 |        0 |    100% |           |
| app/tasks/db/seed.py                                                                                            |       65 |       25 |       22 |        2 |     55% |473-\>487, 489-547, 576 |
| app/tasks/deps.py                                                                                               |      101 |        3 |       30 |        1 |     97% |61-63, 115-\>124 |
| app/tasks/execution/exceptions.py                                                                               |        8 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/celery/models.py                                                                  |       82 |        0 |       14 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/exceptions.py                                                               |        4 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/models.py                                                                   |      660 |      151 |      226 |       21 |     75% |104-106, 113, 153, 171-174, 175-\>exit, 194, 237, 425, 487-\>489, 605-\>611, 700-\>705, 709, 715, 801-\>797, 848, 850, 901-\>916, 960-\>978, 979, 1021-1051, 1072-1086, 1112-1122, 1143-1146, 1225-1227, 1253-1254, 1291-1292, 1326-1327, 1369-\>1413, 1403-\>1369, 1494-1543, 1551-1552, 1556, 1580-1624, 1681-1682, 1754-1755, 1773-1825 |
| app/tasks/execution/models.py                                                                                   |       65 |        0 |       10 |        0 |    100% |           |
| app/tasks/execution/nomad\_lifecycle.py                                                                         |       53 |        0 |       12 |        2 |     97% |125-\>128, 163-\>exit |
| app/tasks/execution/utils.py                                                                                    |       26 |        0 |        6 |        0 |    100% |           |
| app/tasks/logs/constants.py                                                                                     |        1 |        0 |        0 |        0 |    100% |           |
| app/tasks/logs/log\_reader.py                                                                                   |      140 |        8 |       62 |        6 |     92% |106, 131, 134, 181-194, 284, 294-\>286 |
| app/tasks/logs/log\_writer.py                                                                                   |      123 |        8 |       52 |        8 |     91% |116, 226-227, 349, 353, 355-\>350, 357, 537, 543 |
| app/tasks/main.py                                                                                               |       70 |        9 |       16 |        1 |     88% |100-122, 200-201, 207-211 |
| app/tasks/migrations/env.py                                                                                     |       36 |        5 |        4 |        2 |     82% |37-\>44, 64-75, 116 |
| app/tasks/migrations/versions/2024\_09\_18\_1542-04f50684d5d7\_create\_task\_and\_taskhistory\_tables.py        |       34 |       12 |        0 |        0 |     65% |     77-88 |
| app/tasks/migrations/versions/2024\_10\_24\_1528-7920c0e4aa23\_update\_taskbackendenum.py                       |       14 |        2 |        0 |        0 |     86% |     50-51 |
| app/tasks/migrations/versions/2024\_11\_16\_1508-d15d7ea76f80\_use\_enum\_for\_task\_owner.py                   |       16 |        3 |        0 |        0 |     81% |     50-55 |
| app/tasks/migrations/versions/2025\_05\_03\_1359-064c3cec8450\_update\_task\_owner\_enum.py                     |       14 |        2 |        0 |        0 |     86% |     49-50 |
| app/tasks/migrations/versions/2025\_05\_03\_1454-80e592531cd7\_add\_started\_at\_and\_finished\_at\_fields\_.py |       35 |       18 |       10 |        1 |     40% |61-69, 77-115 |
| app/tasks/migrations/versions/2025\_05\_15\_1933-bec093f02c15\_add\_field\_sync\_in\_progress\_started\_at\_.py |       14 |        2 |        0 |        0 |     86% |     46-47 |
| app/tasks/migrations/versions/2025\_05\_20\_1144-68379e926e7c\_update\_taskhistory\_status\_enum.py             |       14 |        2 |        0 |        0 |     86% |     50-51 |
| app/tasks/migrations/versions/2025\_05\_21\_1144-36f2b569e7bb\_create\_dispatchlock\_table.py                   |       14 |        2 |        0 |        0 |     86% |     52-53 |
| app/tasks/migrations/versions/2025\_06\_11\_1021-b4f0b7b50441\_add\_alert\_on\_fail\_field\_to\_task.py         |       12 |        1 |        0 |        0 |     92% |        44 |
| app/tasks/migrations/versions/2025\_08\_05\_2350-19605d228fa3\_add\_anonymize\_mask\_field.py                   |       12 |        1 |        0 |        0 |     92% |        45 |
| app/tasks/migrations/versions/2025\_08\_07\_1757-8f61364b2c2c\_make\_task\_owner\_normal\_string.py             |       14 |        2 |        0 |        0 |     86% |     46-47 |
| app/tasks/migrations/versions/2025\_08\_22\_2153-d39d37d3dcdc\_migrate\_legacy\_generatedtasks.py               |      108 |       79 |       34 |        1 |     21% |59-62, 66-67, 71-74, 78-81, 85-113, 117-128, 155-166, 177, 214-221, 225-227, 231-255 |
| app/tasks/migrations/versions/2025\_09\_16\_1745-3b15a15ac473\_add\_anonymize\_mask\_field\_to\_taskhistory.py  |       16 |        3 |        0 |        0 |     81% |     49-51 |
| app/tasks/migrations/versions/2025\_09\_25\_0448-4e346919fc0f\_add\_output\_files\_path\_to\_task.py            |       12 |        1 |        0 |        0 |     92% |        45 |
| app/tasks/migrations/versions/2025\_10\_07\_1752-0b852d9798ef\_add\_user\_tracking\_fields.py                   |       16 |        3 |        0 |        0 |     81% |     47-49 |
| app/tasks/migrations/versions/2025\_12\_29\_1001-add\_filelock\_requirement\_to\_backup\_tasks.py               |       87 |       64 |       26 |        1 |     21% |54-73, 78-85, 105-136, 143-187 |
| app/tasks/migrations/versions/2026\_03\_04\_2149-bb3edb973603\_.py                                              |       13 |        2 |        0 |        0 |     85% |     53-54 |
| app/tasks/migrations/versions/2026\_04\_14\_1000-taskhistory\_log\_create\_taskhistory\_log\_tables.py          |       17 |        4 |        0 |        0 |     76% |   148-156 |
| app/tasks/migrations/versions/2026\_04\_14\_1752-9ebd648709e8\_add\_execution\_request\_json\_indexes.py        |       27 |       12 |       12 |        2 |     44% |64-69, 73-\>exit, 85-94 |
| app/tasks/migrations/versions/2026\_04\_14\_2218-89e80a316a28\_convert\_execution\_request\_to\_jsonb.py        |       18 |        7 |        4 |        1 |     55% |62-67, 74-78 |
| app/tasks/migrations/versions/2026\_04\_21\_1701-e42ce8324da7\_add\_stale\_to\_taskhistory\_status\_enum.py     |       13 |        2 |        0 |        0 |     85% |     55-56 |
| app/tasks/migrations/versions/2026\_05\_18\_2014-fafdb0445092\_add\_setting\_override\_table.py                 |       18 |        4 |        0 |        0 |     78% |     81-86 |
| app/tasks/migrations/versions/2026\_05\_20\_1500-7d1232c0e3ce\_coerce\_alters\_recursion\_method\_host.py       |       37 |       15 |       10 |        1 |     49% |     75-91 |
| app/tasks/migrations/versions/2026\_06\_02\_1512-6d4cfd37bd3a\_extend\_setting\_class\_enum\_settings\_alert.py |       13 |        3 |        0 |        0 |     77% |     68-73 |
| app/tasks/migrations/versions/2026\_06\_22\_1223-2f5a00236369\_merge\_heads.py                                  |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_06\_22\_1400-abc65df0318a\_extend\_setting\_class\_enum\_anonymizer.py      |       13 |        3 |        0 |        0 |     77% |     71-75 |
| app/tasks/migrations/versions/2026\_06\_22\_1830-c4e8f0a3b1d2\_add\_alert\_detail\_builder\_to\_task.py         |       14 |        1 |        0 |        0 |     93% |        60 |
| app/tasks/models.py                                                                                             |      306 |        3 |       64 |        5 |     98% |616-\>619, 623, 638-\>644, 1050-\>1052, 1062-\>1064, 1087-1088 |
| app/tasks/periodic/crud.py                                                                                      |       26 |        0 |        0 |        0 |    100% |           |
| app/tasks/periodic/deps.py                                                                                      |       11 |        0 |        0 |        0 |    100% |           |
| app/tasks/periodic/models.py                                                                                    |      103 |        5 |       34 |        5 |     93% |196, 231, 285, 301, 370 |
| app/tasks/periodic/routes.py                                                                                    |       56 |        4 |       12 |        3 |     90% |64-68, 111-\>113, 133-136 |
| app/tasks/routes.py                                                                                             |      227 |       28 |       44 |        2 |     87% |139-143, 200, 221-227, 260, 316, 323, 367-368, 394, 434, 453, 593, 617, 630-631, 639-642, 665, 672, 678, 694-695 |
| app/tasks/settings/routes.py                                                                                    |       10 |        0 |        0 |        0 |    100% |           |
| **TOTAL**                                                                                                       | **22239** | **2588** | **5158** |  **497** | **86%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://github.com/percona/SEP/raw/python-coverage-comment-action-data/badge.svg)](https://github.com/percona/SEP/tree/python-coverage-comment-action-data)

This is the one to use if your repository is private or if you don't want to customize anything.



## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.