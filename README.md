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
| app/core/auth/providers/casdoor.py                                                                          |      123 |       65 |     47% |53, 126-127, 139, 187, 215-219, 241-248, 276-296, 304-305, 326-335, 351-352, 372-391, 409-414, 424-425, 436-439, 451-455, 467-471 |
| app/core/auth/utils.py                                                                                      |        5 |        0 |    100% |           |
| app/core/celery/config.py                                                                                   |       23 |        0 |    100% |           |
| app/core/celery/crud.py                                                                                     |       26 |        4 |     85% |91-98, 139 |
| app/core/celery/db.py                                                                                       |        8 |        0 |    100% |           |
| app/core/celery/deps.py                                                                                     |       10 |        0 |    100% |           |
| app/core/celery/models.py                                                                                   |       36 |        2 |     94% |   72, 135 |
| app/core/celery/utils.py                                                                                    |       30 |       21 |     30% |    80-124 |
| app/core/config.py                                                                                          |      171 |        4 |     98% |382, 436, 510, 523 |
| app/core/db/config.py                                                                                       |       17 |        0 |    100% |           |
| app/core/db/crud.py                                                                                         |      268 |       39 |     85% |145, 192, 194, 325-342, 360, 365, 382, 384, 495-510, 735-740, 768-770, 832-834, 1073-1077 |
| app/core/db/models.py                                                                                       |       14 |        0 |    100% |           |
| app/core/db/sql\_types.py                                                                                   |       37 |        0 |    100% |           |
| app/core/db/utils.py                                                                                        |       54 |        4 |     93% |76, 191, 220, 223 |
| app/core/exceptions.py                                                                                      |       29 |        1 |     97% |        69 |
| app/core/log.py                                                                                             |       21 |        0 |    100% |           |
| app/core/middleware/log\_context.py                                                                         |       26 |        0 |    100% |           |
| app/core/middleware/security\_headers.py                                                                    |      105 |        0 |    100% |           |
| app/core/models.py                                                                                          |       21 |        0 |    100% |           |
| app/core/pmm.py                                                                                             |       45 |        1 |     98% |        53 |
| app/core/requests/registry.py                                                                               |       49 |       14 |     71% |101, 112, 125-142 |
| app/core/requests/remote\_api.py                                                                            |      176 |       17 |     90% |342-344, 375-391, 400 |
| app/core/security.py                                                                                        |        4 |        0 |    100% |           |
| app/core/utils/async\_run.py                                                                                |       13 |        0 |    100% |           |
| app/core/utils/cache.py                                                                                     |       92 |       11 |     88% |60-62, 151, 197-200, 208-209, 223 |
| app/core/utils/date\_time.py                                                                                |        8 |        0 |    100% |           |
| app/core/utils/dict.py                                                                                      |       27 |        4 |     85% |   160-163 |
| app/core/utils/fields.py                                                                                    |      146 |        5 |     97% |140, 206-207, 374, 378 |
| app/core/utils/imports.py                                                                                   |       24 |        0 |    100% |           |
| app/core/utils/iterators.py                                                                                 |       18 |        0 |    100% |           |
| app/core/utils/lazy.py                                                                                      |       31 |        0 |    100% |           |
| app/core/utils/openapi.py                                                                                   |       16 |        0 |    100% |           |
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
| app/inventory/routes/services.py                                                                            |       43 |        4 |     91% |   142-151 |
| app/inventory/routes/tables.py                                                                              |       26 |        0 |    100% |           |
| app/main.py                                                                                                 |       61 |       31 |     49% |52-58, 108-111, 116-120, 124-178 |
| app/models.py                                                                                               |       74 |        4 |     95% |   208-213 |
| app/sep/api/router.py                                                                                       |        7 |        0 |    100% |           |
| app/sep/celery.py                                                                                           |      118 |       27 |     77% |142, 170-218, 224 |
| app/sep/clients/pmm.py                                                                                      |      247 |       10 |     96% |218, 485, 487, 561, 597-598, 732-733, 754-755 |
| app/sep/config.py                                                                                           |      196 |       12 |     94% |102, 123-125, 224, 301, 318, 332, 336, 338, 340, 454 |
| app/sep/connectivity.py                                                                                     |       72 |        1 |     99% |       103 |
| app/sep/crud.py                                                                                             |       47 |        0 |    100% |           |
| app/sep/db/engine.py                                                                                        |        8 |        0 |    100% |           |
| app/sep/db/seed.py                                                                                          |       29 |       16 |     45% | 65-79, 97 |
| app/sep/deps.py                                                                                             |      281 |       10 |     96% |318, 321-322, 340, 805-806, 986-989 |
| app/sep/exceptions.py                                                                                       |       13 |        0 |    100% |           |
| app/sep/inventory.py                                                                                        |       97 |        9 |     91% |81, 92, 229, 286, 304, 326, 363, 385, 419 |
| app/sep/main.py                                                                                             |      154 |       11 |     93% |74-76, 92-106, 368-372 |
| app/sep/middleware/csrf.py                                                                                  |       48 |        1 |     98% |       129 |
| app/sep/middleware/messages/\_middleware.py                                                                 |       28 |        0 |    100% |           |
| app/sep/middleware/messages/\_utils.py                                                                      |       53 |       10 |     81% |85, 118, 259-266 |
| app/sep/middleware/messages/config.py                                                                       |        9 |        0 |    100% |           |
| app/sep/middleware/messages/models.py                                                                       |       31 |        0 |    100% |           |
| app/sep/migrations/\_discovery.py                                                                           |       33 |        2 |     94% |   70, 103 |
| app/sep/migrations/env.py                                                                                   |       38 |        5 |     87% |67-78, 120 |
| app/sep/migrations/versions/2024\_10\_07\_1450-7f4dec8bc76a\_create\_sync\_tables.py                        |       26 |        8 |     69% |     69-76 |
| app/sep/migrations/versions/2024\_10\_08\_2047-eeac2926bbea\_remove\_task\_history\_id\_field.py            |       12 |        1 |     92% |        45 |
| app/sep/migrations/versions/2025\_08\_08\_1005-9307f0f5ee54\_create\_snippet\_table.py                      |       16 |        3 |     81% |     59-61 |
| app/sep/migrations/versions/2026\_03\_02\_1612-810c31754b54\_add\_index\_for\_syncinstance\_syncer.py       |       12 |        1 |     92% |        45 |
| app/sep/models.py                                                                                           |       48 |        1 |     98% |       247 |
| app/sep/plugins/alert\_troubleshooting/deps.py                                                              |      135 |       20 |     85% |122, 236-237, 259-261, 280, 363-364, 388-394, 418-420, 444-447, 474 |
| app/sep/plugins/alert\_troubleshooting/routes.py                                                            |       66 |        5 |     92% |141-146, 197-198 |
| app/sep/plugins/alerts/config.py                                                                            |       19 |        0 |    100% |           |
| app/sep/plugins/alerts/crud.py                                                                              |       12 |        0 |    100% |           |
| app/sep/plugins/alerts/deps.py                                                                              |       87 |        0 |    100% |           |
| app/sep/plugins/alerts/loader.py                                                                            |       22 |        0 |    100% |           |
| app/sep/plugins/alerts/migrations/versions/2026\_04\_20\_1817-d21ad387df7a\_create\_alert\_backup\_table.py |       14 |        0 |    100% |           |
| app/sep/plugins/alerts/models.py                                                                            |       21 |        0 |    100% |           |
| app/sep/plugins/alerts/restore.py                                                                           |       93 |        3 |     97% |69, 74, 143 |
| app/sep/plugins/alerts/routes.py                                                                            |      121 |       20 |     83% |66-73, 120-122, 297-298, 338-356 |
| app/sep/plugins/alters/deps.py                                                                              |      169 |        0 |    100% |           |
| app/sep/plugins/alters/models.py                                                                            |       26 |        0 |    100% |           |
| app/sep/plugins/alters/pre\_checks.py                                                                       |      236 |      236 |      0% |    27-638 |
| app/sep/plugins/alters/routes.py                                                                            |      107 |        0 |    100% |           |
| app/sep/plugins/archives/deps.py                                                                            |       63 |        7 |     89% |119-122, 132, 134, 258 |
| app/sep/plugins/archives/models.py                                                                          |       91 |        3 |     97% |138, 169, 221 |
| app/sep/plugins/archives/payload                                                                            |      195 |      135 |     31% |44-235, 240-246, 295, 300-309, 385-400, 405-409, 413 |
| app/sep/plugins/archives/routes.py                                                                          |       78 |        6 |     92% |134, 136, 138, 212-217 |
| app/sep/plugins/atw/models.py                                                                               |       26 |        1 |     96% |        74 |
| app/sep/plugins/atw/routes.py                                                                               |       23 |        9 |     61% |     48-72 |
| app/sep/plugins/backup/deps.py                                                                              |       74 |       11 |     85% |100, 137, 191, 197-199, 203, 205, 208-209, 290 |
| app/sep/plugins/backup/models.py                                                                            |       91 |        1 |     99% |       286 |
| app/sep/plugins/backup/restore/deps.py                                                                      |       57 |       38 |     33% |53-104, 132-153, 177, 193-198, 231 |
| app/sep/plugins/backup/restore/models.py                                                                    |       73 |        1 |     99% |       198 |
| app/sep/plugins/backup/restore/routes.py                                                                    |       65 |       37 |     43% |58, 74-80, 96-150, 171-180, 195-200, 217-219 |
| app/sep/plugins/backup/routes.py                                                                            |       76 |        6 |     92% |74, 178-179, 232-237 |
| app/sep/plugins/backup\_mongo/deps.py                                                                       |       69 |       49 |     29% |52, 61-72, 86-99, 112-152, 168-185, 230, 246-248, 281 |
| app/sep/plugins/backup\_mongo/models.py                                                                     |       89 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/deps.py                                                               |      108 |       83 |     23% |50-63, 68-85, 93-107, 133-153, 180-185, 208-213, 234-255, 269-287, 297-306, 334, 351-362, 397 |
| app/sep/plugins/backup\_mongo/restore/models.py                                                             |       31 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/routes.py                                                             |      133 |      102 |     23% |57-70, 84-111, 120-138, 155, 174-203, 224-308, 330-339, 355-360, 378-380 |
| app/sep/plugins/backup\_mongo/routes.py                                                                     |      104 |       75 |     28% |74-97, 106, 122-173, 187-248, 269-278, 292-295 |
| app/sep/plugins/backup\_pg/deps.py                                                                          |       45 |        1 |     98% |       180 |
| app/sep/plugins/backup\_pg/models.py                                                                        |       22 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/routes.py                                                                        |       58 |        0 |    100% |           |
| app/sep/plugins/checksums/api\_routes.py                                                                    |       34 |        0 |    100% |           |
| app/sep/plugins/checksums/deps.py                                                                           |      140 |       61 |     56% |73-84, 100-138, 215, 423-425, 528-533, 549-576, 589-616, 627, 657 |
| app/sep/plugins/checksums/models.py                                                                         |       51 |        0 |    100% |           |
| app/sep/plugins/checksums/routes.py                                                                         |       65 |       33 |     49% |59-60, 107-157, 177-185, 200-206, 222-223 |
| app/sep/plugins/checksums/schema.py                                                                         |        3 |        0 |    100% |           |
| app/sep/plugins/dipper/constants.py                                                                         |       10 |        0 |    100% |           |
| app/sep/plugins/dipper/deps.py                                                                              |      107 |       75 |     30% |69-77, 88, 104-109, 123-124, 140-149, 175-204, 215-223, 239-254, 274-282, 294-301, 327-335 |
| app/sep/plugins/dipper/models.py                                                                            |        6 |        0 |    100% |           |
| app/sep/plugins/dipper/payloads/pcs-collect-pmm-mysql.py                                                    |      291 |      250 |     14% |   245-847 |
| app/sep/plugins/dipper/routes.py                                                                            |       66 |       44 |     33% |74-190, 207-212 |
| app/sep/plugins/framework/api.py                                                                            |       14 |        0 |    100% |           |
| app/sep/plugins/framework/connectivity.py                                                                   |       23 |        0 |    100% |           |
| app/sep/plugins/framework/schema.py                                                                         |      106 |        0 |    100% |           |
| app/sep/plugins/inventory/deps.py                                                                           |       51 |        7 |     86% |   202-226 |
| app/sep/plugins/inventory/models.py                                                                         |       27 |        1 |     96% |        78 |
| app/sep/plugins/inventory/routes.py                                                                         |      160 |        0 |    100% |           |
| app/sep/plugins/inventory/sync.py                                                                           |       31 |        0 |    100% |           |
| app/sep/plugins/report/deps.py                                                                              |       28 |        0 |    100% |           |
| app/sep/plugins/report/models.py                                                                            |      111 |        0 |    100% |           |
| app/sep/plugins/report/routes.py                                                                            |       39 |        0 |    100% |           |
| app/sep/plugins/report/service.py                                                                           |      378 |       16 |     96% |126, 130, 331, 345-346, 407, 444-445, 447, 451, 553, 558, 566, 575, 638, 645 |
| app/sep/plugins/snippets/deps.py                                                                            |       72 |       39 |     46% |61-64, 83-94, 103-106, 132-134, 163-165, 194-196, 214-223, 243-259, 278-283 |
| app/sep/plugins/snippets/routes.py                                                                          |      101 |       61 |     40% |65-67, 85-120, 130-132, 143-145, 153-155, 163-168, 202-206, 210-215, 219-255, 266-281 |
| app/sep/plugins/tasks/deps.py                                                                               |        5 |        0 |    100% |           |
| app/sep/plugins/tasks/models.py                                                                             |        6 |        0 |    100% |           |
| app/sep/plugins/tasks/routes.py                                                                             |       56 |        0 |    100% |           |
| app/sep/routes/artifacts.py                                                                                 |       31 |        1 |     97% |        66 |
| app/sep/routes/download\_files.py                                                                           |       37 |        0 |    100% |           |
| app/sep/routes/execution\_events.py                                                                         |       14 |        0 |    100% |           |
| app/sep/routes/inventory\_ajax.py                                                                           |       29 |        0 |    100% |           |
| app/sep/routes/periodic\_tasks.py                                                                           |       31 |        1 |     97% |        83 |
| app/sep/routes/stop\_task.py                                                                                |       19 |        0 |    100% |           |
| app/sep/routes/stream\_logs.py                                                                              |       78 |       29 |     63% |86, 91-98, 109-132, 185-207 |
| app/sep/snippets/config.py                                                                                  |      128 |       20 |     84% |122, 194-203, 215, 265, 347-352, 433, 444, 460-463 |
| app/sep/snippets/crud.py                                                                                    |       15 |        0 |    100% |           |
| app/sep/snippets/forms.py                                                                                   |      242 |       10 |     96% |179, 670-673, 829, 831, 842, 950, 957 |
| app/sep/snippets/models/meta.py                                                                             |      139 |        1 |     99% |       250 |
| app/sep/snippets/models/snippet.py                                                                          |      365 |       40 |     89% |226, 273, 276-277, 343-350, 358, 373-384, 396-397, 590, 630-642, 723-725, 799-801, 876, 881, 907-918 |
| app/sep/snippets/utils.py                                                                                   |       28 |        0 |    100% |           |
| app/sep/sync/exceptions.py                                                                                  |       25 |        0 |    100% |           |
| app/sep/sync/models.py                                                                                      |      348 |       60 |     83% |75-84, 98-100, 119, 267-269, 330, 390-391, 424, 478-480, 537, 567, 583, 603-607, 708, 722, 742-743, 823, 837, 859-860, 941, 954, 978-980, 1052, 1065, 1085-1086, 1161, 1305-1307, 1316, 1361-1362, 1365, 1371-1373, 1378-1384, 1388 |
| app/sep/sync/syncers/mysql/payload.py                                                                       |      175 |       47 |     73% |240-244, 249-254, 267-273, 277-300, 373, 394-402, 421 |
| app/sep/sync/syncers/mysql/syncer.py                                                                        |      243 |       10 |     96% |114, 368, 624, 646, 664, 753-762 |
| app/sep/sync/syncers/pmm.py                                                                                 |       93 |       22 |     76% |83-87, 107-110, 121, 176-184, 232, 234, 236-252, 291-294, 344 |
| app/sep/tasks.py                                                                                            |       31 |        0 |    100% |           |
| app/sep/utils/decorators.py                                                                                 |       10 |        0 |    100% |           |
| app/sep/utils/forms.py                                                                                      |       20 |        0 |    100% |           |
| app/sep/utils/jinja.py                                                                                      |       61 |       10 |     84% |105, 124, 135-140, 171-172 |
| app/sep/utils/static.py                                                                                     |       10 |        0 |    100% |           |
| app/tasks/anonymizer/anonymize.py                                                                           |       50 |        0 |    100% |           |
| app/tasks/anonymizer/config.py                                                                              |       27 |        1 |     96% |        68 |
| app/tasks/anonymizer/entities.py                                                                            |       28 |        0 |    100% |           |
| app/tasks/celery.py                                                                                         |      282 |        9 |     97% |297, 307-308, 331-333, 654, 677-678 |
| app/tasks/config.py                                                                                         |       22 |        0 |    100% |           |
| app/tasks/connectivity/constants.py                                                                         |        4 |        0 |    100% |           |
| app/tasks/connectivity/models.py                                                                            |       11 |        0 |    100% |           |
| app/tasks/connectivity/payload.py                                                                           |       54 |        1 |     98% |       133 |
| app/tasks/connectivity/routes.py                                                                            |       15 |        0 |    100% |           |
| app/tasks/connectivity/service.py                                                                           |      103 |        2 |     98% |  178, 348 |
| app/tasks/crud.py                                                                                           |      160 |        1 |     99% |       124 |
| app/tasks/db/engine.py                                                                                      |        8 |        0 |    100% |           |
| app/tasks/db/seed.py                                                                                        |       65 |       25 |     62% |489-547, 576 |
| app/tasks/deps.py                                                                                           |       91 |        3 |     97% |     60-62 |
| app/tasks/execution/exceptions.py                                                                           |        8 |        0 |    100% |           |
| app/tasks/execution/executors/celery/models.py                                                              |       82 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/exceptions.py                                                           |        4 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/models.py                                                               |      655 |      151 |     77% |104-106, 113, 153, 171-174, 194, 237, 425, 709, 715, 848, 850, 979, 1021-1051, 1072-1086, 1112-1122, 1143-1146, 1225-1227, 1253-1254, 1291-1292, 1326-1327, 1494-1543, 1551-1552, 1556, 1580-1624, 1681-1682, 1754-1755, 1773-1825 |
| app/tasks/execution/models.py                                                                               |       63 |        1 |     98% |       229 |
| app/tasks/execution/utils.py                                                                                |       26 |        0 |    100% |           |
| app/tasks/logs/log\_reader.py                                                                               |       54 |        0 |    100% |           |
| app/tasks/logs/log\_writer.py                                                                               |      123 |        8 |     93% |116, 226-227, 349, 353, 357, 537, 543 |
| app/tasks/main.py                                                                                           |       58 |       11 |     81% |57-60, 84-85, 134-135, 142-146 |
| app/tasks/models.py                                                                                         |      291 |        3 |     99% |591, 1040-1041 |
| app/tasks/periodic/crud.py                                                                                  |       26 |        0 |    100% |           |
| app/tasks/periodic/deps.py                                                                                  |       11 |        0 |    100% |           |
| app/tasks/periodic/models.py                                                                                |      103 |        5 |     95% |196, 231, 285, 301, 370 |
| app/tasks/periodic/routes.py                                                                                |       56 |        4 |     93% |64-68, 133-136 |
| app/tasks/routes.py                                                                                         |      205 |       29 |     86% |122-126, 183, 204-211, 243, 292-300, 306, 350-351, 378-379, 407-408, 427, 560, 575, 584-595, 611-612 |
| **TOTAL**                                                                                                   | **13740** | **2322** | **83%** |           |


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