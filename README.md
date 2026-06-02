# Repository Coverage



| Name                                                                                                        |    Stmts |     Miss |   Cover |   Missing |
|------------------------------------------------------------------------------------------------------------ | -------: | -------: | ------: | --------: |
| app/api/deps.py                                                                                             |       48 |        0 |    100% |           |
| app/api/main.py                                                                                             |        6 |        0 |    100% |           |
| app/api/routes/config.py                                                                                    |        9 |        0 |    100% |           |
| app/api/routes/oauth.py                                                                                     |       60 |        0 |    100% |           |
| app/api/routes/users.py                                                                                     |       21 |        0 |    100% |           |
| app/celery.py                                                                                               |       32 |        4 |     88% | 45, 51-53 |
| app/core/alerts/config.py                                                                                   |       34 |        0 |    100% |           |
| app/core/alerts/models.py                                                                                   |       57 |        0 |    100% |           |
| app/core/alerts/providers/pagerduty.py                                                                      |       35 |        1 |     97% |       110 |
| app/core/auth/exceptions.py                                                                                 |       11 |        0 |    100% |           |
| app/core/auth/models.py                                                                                     |       63 |        1 |     98% |       170 |
| app/core/auth/providers/casdoor.py                                                                          |      123 |       61 |     50% |53, 126-127, 139, 187, 218-219, 241-248, 276-296, 304-305, 326-335, 351-352, 372-391, 409-414, 424-425, 439, 451-455, 467-471 |
| app/core/auth/utils.py                                                                                      |        5 |        0 |    100% |           |
| app/core/celery/config.py                                                                                   |       23 |        0 |    100% |           |
| app/core/celery/crud.py                                                                                     |       26 |        4 |     85% |91-98, 139 |
| app/core/celery/db.py                                                                                       |        8 |        0 |    100% |           |
| app/core/celery/deps.py                                                                                     |       10 |        0 |    100% |           |
| app/core/celery/models.py                                                                                   |       36 |        2 |     94% |   72, 135 |
| app/core/celery/utils.py                                                                                    |       30 |       21 |     30% |    80-124 |
| app/core/config.py                                                                                          |      193 |        6 |     97% |393, 427, 470, 544, 557, 598 |
| app/core/db/config.py                                                                                       |       17 |        0 |    100% |           |
| app/core/db/crud.py                                                                                         |      269 |       29 |     89% |193, 326-343, 361, 366, 383, 385, 496-511, 769-771, 834, 1074-1078 |
| app/core/db/models.py                                                                                       |       14 |        0 |    100% |           |
| app/core/db/sql\_types.py                                                                                   |       37 |        0 |    100% |           |
| app/core/db/utils.py                                                                                        |       54 |        4 |     93% |76, 191, 220, 223 |
| app/core/exceptions.py                                                                                      |       32 |        0 |    100% |           |
| app/core/log.py                                                                                             |       21 |        0 |    100% |           |
| app/core/middleware/log\_context.py                                                                         |       26 |        0 |    100% |           |
| app/core/middleware/security\_headers.py                                                                    |      105 |        0 |    100% |           |
| app/core/models.py                                                                                          |       21 |        0 |    100% |           |
| app/core/pmm.py                                                                                             |       50 |        1 |     98% |        53 |
| app/core/requests/registry.py                                                                               |       49 |       14 |     71% |101, 112, 125-142 |
| app/core/requests/remote\_api.py                                                                            |      215 |        8 |     96% |96, 115, 414, 454-457, 465 |
| app/core/security.py                                                                                        |        4 |        0 |    100% |           |
| app/core/settings\_override/api/models.py                                                                   |       11 |        0 |    100% |           |
| app/core/settings\_override/api/routes.py                                                                   |      106 |       13 |     88% |107, 236, 267-270, 296, 337, 387, 469-482 |
| app/core/settings\_override/cache.py                                                                        |       28 |        0 |    100% |           |
| app/core/settings\_override/lifecycle.py                                                                    |       52 |        2 |     96% |   177-178 |
| app/core/settings\_override/manager.py                                                                      |        5 |        0 |    100% |           |
| app/core/settings\_override/models.py                                                                       |       19 |        0 |    100% |           |
| app/core/settings\_override/proxy.py                                                                        |       20 |        0 |    100% |           |
| app/core/settings\_override/registry.py                                                                     |       83 |        0 |    100% |           |
| app/core/utils/async\_run.py                                                                                |       13 |        0 |    100% |           |
| app/core/utils/cache.py                                                                                     |       92 |       11 |     88% |60-62, 151, 197-200, 208-209, 223 |
| app/core/utils/date\_time.py                                                                                |        8 |        0 |    100% |           |
| app/core/utils/dict.py                                                                                      |       27 |        4 |     85% |   160-163 |
| app/core/utils/fields.py                                                                                    |      148 |        5 |     97% |140, 206-207, 374, 378 |
| app/core/utils/imports.py                                                                                   |       28 |        0 |    100% |           |
| app/core/utils/iterators.py                                                                                 |       18 |        0 |    100% |           |
| app/core/utils/lazy.py                                                                                      |       31 |        0 |    100% |           |
| app/core/utils/openapi.py                                                                                   |      129 |        6 |     95% |78-79, 155, 162-163, 242 |
| app/core/utils/path.py                                                                                      |        8 |        0 |    100% |           |
| app/core/utils/pydantic.py                                                                                  |       49 |        0 |    100% |           |
| app/core/utils/serialization.py                                                                             |        7 |        0 |    100% |           |
| app/core/utils/strings.py                                                                                   |       24 |        3 |     88% |     64-69 |
| app/inventory/config.py                                                                                     |       11 |        0 |    100% |           |
| app/inventory/constants.py                                                                                  |        2 |        0 |    100% |           |
| app/inventory/crud.py                                                                                       |       16 |        0 |    100% |           |
| app/inventory/db.py                                                                                         |        7 |        1 |     86% |        40 |
| app/inventory/deps.py                                                                                       |       24 |        3 |     88% |     38-40 |
| app/inventory/main.py                                                                                       |       28 |        9 |     68% |39-42, 73-74, 78-82 |
| app/inventory/models.py                                                                                     |       71 |        0 |    100% |           |
| app/inventory/routes/nodes.py                                                                               |       42 |        0 |    100% |           |
| app/inventory/routes/schemas.py                                                                             |       38 |        0 |    100% |           |
| app/inventory/routes/services.py                                                                            |       43 |        2 |     95% |  142, 151 |
| app/inventory/routes/tables.py                                                                              |       26 |        0 |    100% |           |
| app/main.py                                                                                                 |       78 |       27 |     65% |185-188, 193-197, 201-255 |
| app/models.py                                                                                               |       74 |        4 |     95% |   208-213 |
| app/sep/api/constants.py                                                                                    |        2 |        0 |    100% |           |
| app/sep/api/host\_resolution.py                                                                             |        9 |        0 |    100% |           |
| app/sep/api/openapi.py                                                                                      |        4 |        0 |    100% |           |
| app/sep/api/router.py                                                                                       |       31 |        0 |    100% |           |
| app/sep/api/routes/dashboard.py                                                                             |       34 |        0 |    100% |           |
| app/sep/api/routes/hosts.py                                                                                 |       21 |        0 |    100% |           |
| app/sep/api/routes/services.py                                                                              |       13 |        0 |    100% |           |
| app/sep/api/routes/settings.py                                                                              |        8 |        0 |    100% |           |
| app/sep/api/routes/task\_history.py                                                                         |       13 |        0 |    100% |           |
| app/sep/api/routes/task\_stats.py                                                                           |       13 |        0 |    100% |           |
| app/sep/api/task\_history\_merge.py                                                                         |       40 |        4 |     90% |53, 57-58, 64 |
| app/sep/artifact\_constants.py                                                                              |        4 |        0 |    100% |           |
| app/sep/celery.py                                                                                           |      118 |       28 |     76% |97, 142, 170-218, 224 |
| app/sep/clients/pmm.py                                                                                      |      247 |       10 |     96% |218, 485, 487, 561, 597-598, 732-733, 754-755 |
| app/sep/config.py                                                                                           |      212 |        9 |     96% |119, 278, 355, 372, 386, 390, 392, 394, 508 |
| app/sep/connectivity.py                                                                                     |       77 |        1 |     99% |       103 |
| app/sep/crud.py                                                                                             |       47 |        0 |    100% |           |
| app/sep/db/engine.py                                                                                        |        8 |        0 |    100% |           |
| app/sep/db/seed.py                                                                                          |       29 |       16 |     45% | 65-79, 97 |
| app/sep/deps.py                                                                                             |      295 |       10 |     97% |375, 378-379, 397, 869-870, 1050-1053 |
| app/sep/exceptions.py                                                                                       |       13 |        0 |    100% |           |
| app/sep/inventory.py                                                                                        |       97 |        8 |     92% |81, 92, 229, 286, 326, 363, 385, 419 |
| app/sep/main.py                                                                                             |      171 |        7 |     96% |83-85, 169, 478-482 |
| app/sep/middleware/csrf.py                                                                                  |       48 |        1 |     98% |       129 |
| app/sep/middleware/messages/\_middleware.py                                                                 |       28 |        0 |    100% |           |
| app/sep/middleware/messages/\_utils.py                                                                      |       54 |        9 |     83% |119, 261-268 |
| app/sep/middleware/messages/config.py                                                                       |       12 |        0 |    100% |           |
| app/sep/middleware/messages/models.py                                                                       |       31 |        0 |    100% |           |
| app/sep/migrations/\_discovery.py                                                                           |       33 |        2 |     94% |   70, 103 |
| app/sep/migrations/env.py                                                                                   |       39 |        5 |     87% |68-79, 121 |
| app/sep/migrations/versions/2024\_10\_07\_1450-7f4dec8bc76a\_create\_sync\_tables.py                        |       26 |        8 |     69% |     69-76 |
| app/sep/migrations/versions/2024\_10\_08\_2047-eeac2926bbea\_remove\_task\_history\_id\_field.py            |       12 |        1 |     92% |        45 |
| app/sep/migrations/versions/2025\_08\_08\_1005-9307f0f5ee54\_create\_snippet\_table.py                      |       16 |        3 |     81% |     59-61 |
| app/sep/migrations/versions/2026\_03\_02\_1612-810c31754b54\_add\_index\_for\_syncinstance\_syncer.py       |       12 |        1 |     92% |        45 |
| app/sep/migrations/versions/2026\_05\_18\_2014-ed97b99eef38\_add\_setting\_override\_table.py               |       18 |        4 |     78% |     81-86 |
| app/sep/models.py                                                                                           |       48 |        1 |     98% |       247 |
| app/sep/plugins/alert\_troubleshooting/api\_routes.py                                                       |       23 |        4 |     83% |64-65, 73-80 |
| app/sep/plugins/alert\_troubleshooting/deps.py                                                              |      135 |       18 |     87% |122, 237, 259-261, 280, 364, 388-394, 418-420, 444-447, 474 |
| app/sep/plugins/alert\_troubleshooting/models.py                                                            |        7 |        0 |    100% |           |
| app/sep/plugins/alert\_troubleshooting/routes.py                                                            |       67 |        5 |     93% |143-148, 199-200 |
| app/sep/plugins/alert\_troubleshooting/schema.py                                                            |        2 |        0 |    100% |           |
| app/sep/plugins/alerts/api\_routes.py                                                                       |      117 |       16 |     86% |109, 130-133, 177-187 |
| app/sep/plugins/alerts/config.py                                                                            |       19 |        0 |    100% |           |
| app/sep/plugins/alerts/crud.py                                                                              |        6 |        0 |    100% |           |
| app/sep/plugins/alerts/deps.py                                                                              |       87 |        0 |    100% |           |
| app/sep/plugins/alerts/loader.py                                                                            |       22 |        0 |    100% |           |
| app/sep/plugins/alerts/migrations/versions/2026\_04\_20\_1817-d21ad387df7a\_create\_alert\_backup\_table.py |       14 |        0 |    100% |           |
| app/sep/plugins/alerts/models.py                                                                            |       22 |        0 |    100% |           |
| app/sep/plugins/alerts/restore.py                                                                           |      102 |        3 |     97% |95, 100, 169 |
| app/sep/plugins/alerts/routes.py                                                                            |      111 |       12 |     89% |97-99, 280-281, 321-339 |
| app/sep/plugins/alerts/schemas.py                                                                           |       19 |        0 |    100% |           |
| app/sep/plugins/alters/deps.py                                                                              |      169 |        0 |    100% |           |
| app/sep/plugins/alters/models.py                                                                            |       26 |        0 |    100% |           |
| app/sep/plugins/alters/pre\_checks.py                                                                       |      236 |      236 |      0% |    27-638 |
| app/sep/plugins/alters/routes.py                                                                            |      107 |        0 |    100% |           |
| app/sep/plugins/archives/api\_routes.py                                                                     |       31 |        0 |    100% |           |
| app/sep/plugins/archives/constants.py                                                                       |        5 |        0 |    100% |           |
| app/sep/plugins/archives/deps.py                                                                            |      121 |        2 |     98% |  430, 462 |
| app/sep/plugins/archives/models.py                                                                          |       76 |        0 |    100% |           |
| app/sep/plugins/archives/payload                                                                            |      195 |      135 |     31% |44-235, 240-246, 295, 300-309, 385-400, 405-409, 413 |
| app/sep/plugins/archives/routes.py                                                                          |       91 |        3 |     97% |142, 144, 146 |
| app/sep/plugins/archives/schema.py                                                                          |        5 |        0 |    100% |           |
| app/sep/plugins/atw/api\_routes.py                                                                          |       42 |        0 |    100% |           |
| app/sep/plugins/atw/models.py                                                                               |       34 |        0 |    100% |           |
| app/sep/plugins/atw/routes.py                                                                               |       24 |        9 |     62% |     49-80 |
| app/sep/plugins/atw/schema.py                                                                               |       13 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/api\_routes.py                                                                |       47 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/deps.py                                                                       |      183 |       60 |     67% |83, 106-119, 146-172, 235, 307-308, 374, 440-459, 492-511, 521-522, 597, 635-637, 670 |
| app/sep/plugins/backup\_mongo/models.py                                                                     |      129 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/api\_routes.py                                                        |       44 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/deps.py                                                               |      258 |       58 |     78% |77-90, 107, 109-111, 150, 213, 344-365, 395, 457-458, 498-499, 740-754, 769-770, 839, 937-948, 983 |
| app/sep/plugins/backup\_mongo/restore/models.py                                                             |       72 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/routes.py                                                             |      141 |       36 |     74% |70-71, 79-80, 105-110, 120-125, 142-143, 146-151, 172, 196, 214, 245-246, 252, 289-290, 295-296, 317-318, 348-357, 396-398 |
| app/sep/plugins/backup\_mongo/restore/schema.py                                                             |        5 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/routes.py                                                                     |       83 |       35 |     58% |66, 147-208, 229-238, 252-255 |
| app/sep/plugins/backup\_mongo/schema.py                                                                     |        9 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/api\_routes.py                                                                   |       52 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/deps.py                                                                          |      114 |       11 |     90% |219-221, 336-338, 401, 456-464 |
| app/sep/plugins/backup\_pg/models.py                                                                        |       55 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/routes.py                                                                        |       62 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/schema.py                                                                        |        4 |        0 |    100% |           |
| app/sep/plugins/checksums/api\_routes.py                                                                    |       53 |        9 |     83% |72, 89, 119-121, 159-162 |
| app/sep/plugins/checksums/deps.py                                                                           |      147 |       61 |     59% |74-85, 101-139, 216, 439-441, 548-553, 569-596, 609-636, 647, 677 |
| app/sep/plugins/checksums/models.py                                                                         |       65 |        0 |    100% |           |
| app/sep/plugins/checksums/routes.py                                                                         |       65 |       33 |     49% |59-60, 107-157, 177-185, 200-206, 222-223 |
| app/sep/plugins/checksums/schema.py                                                                         |        3 |        0 |    100% |           |
| app/sep/plugins/dipper/api\_routes.py                                                                       |       61 |        4 |     93% |77-78, 129-130 |
| app/sep/plugins/dipper/constants.py                                                                         |       10 |        0 |    100% |           |
| app/sep/plugins/dipper/deps.py                                                                              |      164 |       41 |     75% |100, 124-126, 147-148, 171-176, 190-191, 242-271, 334-337, 368, 403, 405, 407, 495, 534 |
| app/sep/plugins/dipper/models.py                                                                            |       14 |        0 |    100% |           |
| app/sep/plugins/dipper/payloads/pcs-collect-pmm-mysql.py                                                    |      291 |      250 |     14% |   245-847 |
| app/sep/plugins/dipper/routes.py                                                                            |       67 |       41 |     39% |94-199, 216-221 |
| app/sep/plugins/dipper/schema.py                                                                            |       31 |        1 |     97% |       154 |
| app/sep/plugins/framework/api.py                                                                            |       46 |        2 |     96% |   133-138 |
| app/sep/plugins/framework/cascade.py                                                                        |      183 |        0 |    100% |           |
| app/sep/plugins/framework/connectivity.py                                                                   |       23 |        0 |    100% |           |
| app/sep/plugins/framework/deprecation.py                                                                    |       19 |        0 |    100% |           |
| app/sep/plugins/framework/rules.py                                                                          |      496 |        5 |     99% |312, 317, 322, 534, 850 |
| app/sep/plugins/framework/schema.py                                                                         |      270 |        1 |     99% |      1216 |
| app/sep/plugins/framework/task\_status.py                                                                   |        8 |        0 |    100% |           |
| app/sep/plugins/inventory/api\_routes.py                                                                    |       58 |        0 |    100% |           |
| app/sep/plugins/inventory/deps.py                                                                           |      131 |       13 |     90% |255-279, 372-377, 420, 427 |
| app/sep/plugins/inventory/models.py                                                                         |       29 |        1 |     97% |        93 |
| app/sep/plugins/inventory/routes.py                                                                         |      175 |        0 |    100% |           |
| app/sep/plugins/inventory/schema.py                                                                         |        8 |        0 |    100% |           |
| app/sep/plugins/inventory/sync.py                                                                           |       31 |        0 |    100% |           |
| app/sep/plugins/mysql\_backups/api\_routes.py                                                               |       37 |        0 |    100% |           |
| app/sep/plugins/mysql\_backups/deps.py                                                                      |      124 |        6 |     95% |198, 261, 276, 279-280, 464 |
| app/sep/plugins/mysql\_backups/models.py                                                                    |      136 |        3 |     98% |298, 332, 347 |
| app/sep/plugins/mysql\_backups/restore/deps.py                                                              |       69 |       14 |     80% |73-75, 78-84, 103, 119, 204, 220-225, 258 |
| app/sep/plugins/mysql\_backups/restore/models.py                                                            |       73 |        1 |     99% |       198 |
| app/sep/plugins/mysql\_backups/restore/routes.py                                                            |       65 |        8 |     88% |141-142, 171-180, 217-219 |
| app/sep/plugins/mysql\_backups/routes.py                                                                    |       77 |        6 |     92% |76, 180-181, 234-239 |
| app/sep/plugins/mysql\_backups/schema.py                                                                    |       18 |        0 |    100% |           |
| app/sep/plugins/report/deps.py                                                                              |       28 |        0 |    100% |           |
| app/sep/plugins/report/models.py                                                                            |      111 |        0 |    100% |           |
| app/sep/plugins/report/routes.py                                                                            |       39 |        0 |    100% |           |
| app/sep/plugins/report/service.py                                                                           |      378 |       16 |     96% |126, 130, 331, 345-346, 407, 444-445, 447, 451, 553, 558, 566, 575, 638, 645 |
| app/sep/plugins/snippets/api\_routes.py                                                                     |       98 |        5 |     95% |295, 298-299, 347, 378 |
| app/sep/plugins/snippets/deps.py                                                                            |      139 |       26 |     81% |68, 139-141, 177-180, 208, 239, 268-270, 320-336, 490, 522-529 |
| app/sep/plugins/snippets/models.py                                                                          |       29 |        0 |    100% |           |
| app/sep/plugins/snippets/routes.py                                                                          |       98 |       46 |     53% |80-82, 111, 121, 168-178, 182-218, 229-244, 263-303 |
| app/sep/plugins/snippets/schema.py                                                                          |       54 |        4 |     93% |136-138, 232 |
| app/sep/plugins/tasks/api\_routes.py                                                                        |       25 |        0 |    100% |           |
| app/sep/plugins/tasks/deps.py                                                                               |        5 |        0 |    100% |           |
| app/sep/plugins/tasks/models.py                                                                             |       30 |        1 |     97% |       138 |
| app/sep/plugins/tasks/routes.py                                                                             |       56 |        0 |    100% |           |
| app/sep/plugins/tasks/schema.py                                                                             |        2 |        0 |    100% |           |
| app/sep/routes/artifacts.py                                                                                 |       29 |        1 |     97% |        67 |
| app/sep/routes/download\_files.py                                                                           |       43 |        0 |    100% |           |
| app/sep/routes/execution\_events.py                                                                         |       14 |        0 |    100% |           |
| app/sep/routes/inventory\_ajax.py                                                                           |       29 |        0 |    100% |           |
| app/sep/routes/periodic\_tasks.py                                                                           |       31 |        1 |     97% |        83 |
| app/sep/routes/stop\_task.py                                                                                |       19 |        0 |    100% |           |
| app/sep/routes/stream\_logs.py                                                                              |       78 |       29 |     63% |86, 91-98, 109-132, 185-207 |
| app/sep/snippets/config.py                                                                                  |      130 |       20 |     85% |124, 196-205, 217, 267, 349-354, 435, 446, 462-465 |
| app/sep/snippets/crud.py                                                                                    |       15 |        0 |    100% |           |
| app/sep/snippets/forms.py                                                                                   |      242 |       10 |     96% |179, 670-673, 829, 831, 842, 950, 957 |
| app/sep/snippets/models/meta.py                                                                             |      139 |        1 |     99% |       250 |
| app/sep/snippets/models/snippet.py                                                                          |      365 |       18 |     95% |273, 276-277, 378, 381, 630-642, 723-725, 799-801, 881 |
| app/sep/snippets/utils.py                                                                                   |       32 |        0 |    100% |           |
| app/sep/sync/exceptions.py                                                                                  |       25 |        0 |    100% |           |
| app/sep/sync/models.py                                                                                      |      348 |       49 |     86% |77-84, 98, 100, 119, 267-269, 330, 390-391, 537, 567, 583, 603, 708, 722, 742-743, 823, 837, 859-860, 954, 978-980, 1085-1086, 1161, 1305-1307, 1316, 1361-1362, 1365, 1371-1373, 1378-1384, 1388 |
| app/sep/sync/syncers/mysql/payload.py                                                                       |      175 |       47 |     73% |240-244, 249-254, 267-273, 277-300, 373, 394-402, 421 |
| app/sep/sync/syncers/mysql/syncer.py                                                                        |      243 |       10 |     96% |114, 368, 624, 646, 664, 753-762 |
| app/sep/sync/syncers/pmm.py                                                                                 |       93 |       19 |     80% |83-87, 107-110, 121, 176-184, 234, 236-252, 344 |
| app/sep/tasks.py                                                                                            |       31 |        0 |    100% |           |
| app/sep/utils/decorators.py                                                                                 |       10 |        0 |    100% |           |
| app/sep/utils/forms.py                                                                                      |       20 |        0 |    100% |           |
| app/sep/utils/jinja.py                                                                                      |       61 |       10 |     84% |105, 124, 135-140, 171-172 |
| app/sep/utils/static.py                                                                                     |       10 |        0 |    100% |           |
| app/tasks/anonymizer/anonymize.py                                                                           |       50 |        0 |    100% |           |
| app/tasks/anonymizer/config.py                                                                              |       27 |        1 |     96% |        68 |
| app/tasks/anonymizer/entities.py                                                                            |       28 |        0 |    100% |           |
| app/tasks/celery.py                                                                                         |      290 |        8 |     97% |301, 335-337, 644, 715, 738-739 |
| app/tasks/config.py                                                                                         |       24 |        0 |    100% |           |
| app/tasks/connectivity/constants.py                                                                         |        4 |        0 |    100% |           |
| app/tasks/connectivity/models.py                                                                            |       11 |        0 |    100% |           |
| app/tasks/connectivity/payload.py                                                                           |       68 |        1 |     99% |       162 |
| app/tasks/connectivity/routes.py                                                                            |       16 |        0 |    100% |           |
| app/tasks/connectivity/service.py                                                                           |      103 |        2 |     98% |  178, 348 |
| app/tasks/crud.py                                                                                           |      190 |        1 |     99% |       461 |
| app/tasks/db/engine.py                                                                                      |        8 |        0 |    100% |           |
| app/tasks/db/seed.py                                                                                        |       65 |       25 |     62% |489-547, 576 |
| app/tasks/deps.py                                                                                           |       91 |        3 |     97% |     60-62 |
| app/tasks/execution/exceptions.py                                                                           |        8 |        0 |    100% |           |
| app/tasks/execution/executors/celery/models.py                                                              |       82 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/exceptions.py                                                           |        4 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/models.py                                                               |      655 |      151 |     77% |104-106, 113, 153, 171-174, 194, 237, 425, 709, 715, 848, 850, 979, 1021-1051, 1072-1086, 1112-1122, 1143-1146, 1225-1227, 1253-1254, 1291-1292, 1326-1327, 1494-1543, 1551-1552, 1556, 1580-1624, 1681-1682, 1754-1755, 1773-1825 |
| app/tasks/execution/models.py                                                                               |       65 |        1 |     98% |       229 |
| app/tasks/execution/utils.py                                                                                |       26 |        0 |    100% |           |
| app/tasks/logs/log\_reader.py                                                                               |       54 |        0 |    100% |           |
| app/tasks/logs/log\_writer.py                                                                               |      123 |        8 |     93% |116, 226-227, 349, 353, 357, 537, 543 |
| app/tasks/main.py                                                                                           |       63 |        9 |     86% |65-81, 156-157, 163-167 |
| app/tasks/models.py                                                                                         |      299 |        3 |     99% |607, 1056-1057 |
| app/tasks/periodic/crud.py                                                                                  |       26 |        0 |    100% |           |
| app/tasks/periodic/deps.py                                                                                  |       11 |        0 |    100% |           |
| app/tasks/periodic/models.py                                                                                |      103 |        5 |     95% |196, 231, 285, 301, 370 |
| app/tasks/periodic/routes.py                                                                                |       56 |        4 |     93% |64-68, 133-136 |
| app/tasks/routes.py                                                                                         |      227 |       38 |     83% |141-145, 202, 223-230, 262, 318-319, 325, 369-370, 397-398, 440-441, 460, 591, 615, 628-642, 663-676, 692-693 |
| app/tasks/settings/routes.py                                                                                |       10 |        0 |    100% |           |
| **TOTAL**                                                                                                   | **17287** | **2090** | **88%** |           |


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