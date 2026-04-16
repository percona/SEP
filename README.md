# Repository Coverage



| Name                                              |    Stmts |     Miss |   Cover |   Missing |
|-------------------------------------------------- | -------: | -------: | ------: | --------: |
| app/api/deps.py                                   |       32 |        0 |    100% |           |
| app/api/main.py                                   |        5 |        0 |    100% |           |
| app/api/routes/oauth.py                           |       29 |        0 |    100% |           |
| app/api/routes/users.py                           |       21 |        0 |    100% |           |
| app/celery.py                                     |       32 |        4 |     88% | 45, 51-53 |
| app/core/alerts/config.py                         |       34 |        0 |    100% |           |
| app/core/alerts/models.py                         |       57 |        0 |    100% |           |
| app/core/alerts/providers/pagerduty.py            |       35 |        1 |     97% |       110 |
| app/core/auth/exceptions.py                       |       11 |        0 |    100% |           |
| app/core/auth/models.py                           |       62 |        1 |     98% |       153 |
| app/core/auth/providers/casdoor.py                |      123 |       65 |     47% |53, 126-127, 139, 187, 215-219, 241-248, 276-296, 304-305, 326-335, 351-352, 372-391, 409-414, 424-425, 436-439, 451-455, 467-471 |
| app/core/auth/utils.py                            |        5 |        0 |    100% |           |
| app/core/celery/config.py                         |       23 |        0 |    100% |           |
| app/core/celery/crud.py                           |       26 |        5 |     81% |91-98, 133-139 |
| app/core/celery/db.py                             |        8 |        0 |    100% |           |
| app/core/celery/deps.py                           |       10 |        0 |    100% |           |
| app/core/celery/models.py                         |       36 |        2 |     94% |   72, 135 |
| app/core/celery/utils.py                          |       30 |       21 |     30% |    80-124 |
| app/core/config.py                                |      160 |        4 |     98% |374, 428, 502, 515 |
| app/core/db/config.py                             |       17 |        0 |    100% |           |
| app/core/db/crud.py                               |      268 |       43 |     84% |88-91, 145, 192, 194, 325-342, 360, 365, 382, 384, 418, 495-510, 735-740, 768-770, 832-834, 1073-1077 |
| app/core/db/models.py                             |       14 |        0 |    100% |           |
| app/core/db/sql\_types.py                         |       37 |        0 |    100% |           |
| app/core/db/utils.py                              |       49 |        4 |     92% |66, 154, 183, 186 |
| app/core/exceptions.py                            |       29 |        1 |     97% |        69 |
| app/core/log.py                                   |       21 |        0 |    100% |           |
| app/core/middleware/log\_context.py               |       26 |        0 |    100% |           |
| app/core/middleware/security\_headers.py          |      105 |        0 |    100% |           |
| app/core/models.py                                |       21 |        0 |    100% |           |
| app/core/pmm.py                                   |       31 |        0 |    100% |           |
| app/core/requests/registry.py                     |       49 |       14 |     71% |101, 112, 125-142 |
| app/core/requests/remote\_api.py                  |      176 |       17 |     90% |342-344, 375-391, 400 |
| app/core/security.py                              |        4 |        0 |    100% |           |
| app/core/utils/async\_run.py                      |       13 |        0 |    100% |           |
| app/core/utils/cache.py                           |       92 |       11 |     88% |60-62, 151, 197-200, 208-209, 223 |
| app/core/utils/date\_time.py                      |        8 |        0 |    100% |           |
| app/core/utils/dict.py                            |       27 |        4 |     85% |   160-163 |
| app/core/utils/fields.py                          |      146 |        5 |     97% |140, 206-207, 374, 378 |
| app/core/utils/imports.py                         |       24 |        0 |    100% |           |
| app/core/utils/iterators.py                       |       18 |        2 |     89% |     45-46 |
| app/core/utils/lazy.py                            |       31 |        0 |    100% |           |
| app/core/utils/path.py                            |        8 |        0 |    100% |           |
| app/core/utils/pydantic.py                        |       49 |        0 |    100% |           |
| app/core/utils/serialization.py                   |        7 |        0 |    100% |           |
| app/core/utils/strings.py                         |       24 |        3 |     88% |     64-69 |
| app/inventory/config.py                           |       11 |        0 |    100% |           |
| app/inventory/constants.py                        |        2 |        0 |    100% |           |
| app/inventory/crud.py                             |       16 |        0 |    100% |           |
| app/inventory/db.py                               |        7 |        1 |     86% |        40 |
| app/inventory/deps.py                             |       24 |        3 |     88% |     38-40 |
| app/inventory/main.py                             |       27 |        9 |     67% |38-41, 69-70, 74-78 |
| app/inventory/models.py                           |       71 |        0 |    100% |           |
| app/inventory/routes/nodes.py                     |       42 |        0 |    100% |           |
| app/inventory/routes/schemas.py                   |       38 |        0 |    100% |           |
| app/inventory/routes/services.py                  |       43 |        4 |     91% |   142-151 |
| app/inventory/routes/tables.py                    |       26 |        0 |    100% |           |
| app/main.py                                       |       56 |       31 |     45% |50-56, 74-77, 82-86, 90-144 |
| app/models.py                                     |       74 |        4 |     95% |   208-213 |
| app/sep/api/routes.py                             |       29 |        0 |    100% |           |
| app/sep/celery.py                                 |      118 |       27 |     77% |142, 170-218, 224 |
| app/sep/clients/pmm.py                            |      247 |       10 |     96% |218, 485, 487, 561, 597-598, 732-733, 754-755 |
| app/sep/config.py                                 |      194 |       12 |     94% |102, 123-125, 219, 296, 313, 327, 331, 333, 335, 439 |
| app/sep/connectivity.py                           |       64 |        1 |     98% |        68 |
| app/sep/crud.py                                   |       47 |        0 |    100% |           |
| app/sep/db/engine.py                              |        8 |        0 |    100% |           |
| app/sep/db/seed.py                                |       37 |       23 |     38% |65-79, 101-110, 118 |
| app/sep/deps.py                                   |      260 |       12 |     95% |148-149, 224, 227-228, 246, 711-712, 892-895 |
| app/sep/exceptions.py                             |       13 |        0 |    100% |           |
| app/sep/inventory.py                              |       97 |        9 |     91% |81, 92, 229, 286, 304, 326, 363, 385, 419 |
| app/sep/main.py                                   |      149 |       13 |     91% |69-72, 88-102, 271, 355-359 |
| app/sep/middleware/csrf.py                        |       44 |        1 |     98% |       103 |
| app/sep/middleware/messages/\_middleware.py       |       28 |        0 |    100% |           |
| app/sep/middleware/messages/\_utils.py            |       53 |       10 |     81% |85, 118, 259-266 |
| app/sep/middleware/messages/config.py             |        9 |        0 |    100% |           |
| app/sep/middleware/messages/models.py             |       31 |        0 |    100% |           |
| app/sep/models.py                                 |       48 |        1 |     98% |       247 |
| app/sep/plugins/alert\_troubleshooting/deps.py    |      135 |       20 |     85% |122, 236-237, 259-261, 280, 363-364, 388-394, 418-420, 444-447, 474 |
| app/sep/plugins/alert\_troubleshooting/routes.py  |       66 |        5 |     92% |141-146, 197-198 |
| app/sep/plugins/alerts/backup.py                  |        8 |        0 |    100% |           |
| app/sep/plugins/alerts/config.py                  |       19 |        0 |    100% |           |
| app/sep/plugins/alerts/crud.py                    |       12 |        0 |    100% |           |
| app/sep/plugins/alerts/deps.py                    |       88 |        0 |    100% |           |
| app/sep/plugins/alerts/loader.py                  |       22 |        0 |    100% |           |
| app/sep/plugins/alerts/models.py                  |       14 |        0 |    100% |           |
| app/sep/plugins/alerts/restore.py                 |       94 |        3 |     97% |69, 74, 143 |
| app/sep/plugins/alerts/routes.py                  |      121 |       20 |     83% |66-73, 120-122, 297-298, 338-356 |
| app/sep/plugins/alters/deps.py                    |      169 |        0 |    100% |           |
| app/sep/plugins/alters/models.py                  |       26 |        0 |    100% |           |
| app/sep/plugins/alters/pre\_checks.py             |      236 |      236 |      0% |    27-638 |
| app/sep/plugins/alters/routes.py                  |      107 |        0 |    100% |           |
| app/sep/plugins/archives/deps.py                  |       63 |       10 |     84% |118-121, 131, 133, 223, 225, 227, 255 |
| app/sep/plugins/archives/models.py                |       89 |        3 |     97% |130, 161, 213 |
| app/sep/plugins/archives/routes.py                |       78 |        6 |     92% |134, 136, 138, 212-217 |
| app/sep/plugins/atw/models.py                     |       26 |        1 |     96% |        74 |
| app/sep/plugins/atw/routes.py                     |       23 |        9 |     61% |     48-72 |
| app/sep/plugins/backup/deps.py                    |       74 |       11 |     85% |100, 137, 191, 197-199, 203, 205, 208-209, 290 |
| app/sep/plugins/backup/models.py                  |       91 |        1 |     99% |       286 |
| app/sep/plugins/backup/restore/deps.py            |       57 |       38 |     33% |53-104, 132-153, 177, 193-198, 231 |
| app/sep/plugins/backup/restore/models.py          |       73 |        1 |     99% |       198 |
| app/sep/plugins/backup/restore/routes.py          |       65 |       37 |     43% |58, 74-80, 96-150, 171-180, 195-200, 217-219 |
| app/sep/plugins/backup/routes.py                  |       76 |        6 |     92% |74, 178-179, 232-237 |
| app/sep/plugins/backup\_mongo/deps.py             |       69 |       49 |     29% |52, 61-72, 86-99, 112-152, 168-185, 230, 246-248, 281 |
| app/sep/plugins/backup\_mongo/models.py           |       89 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/deps.py     |      108 |       83 |     23% |50-63, 68-85, 93-107, 133-153, 180-185, 208-213, 234-255, 269-287, 297-306, 334, 351-362, 397 |
| app/sep/plugins/backup\_mongo/restore/models.py   |       31 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/routes.py   |      133 |      102 |     23% |57-70, 84-111, 120-138, 155, 174-203, 224-308, 330-339, 355-360, 378-380 |
| app/sep/plugins/backup\_mongo/routes.py           |      104 |       75 |     28% |74-97, 106, 122-173, 187-248, 269-278, 292-295 |
| app/sep/plugins/backup\_pg/deps.py                |       45 |        1 |     98% |       180 |
| app/sep/plugins/backup\_pg/models.py              |       22 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/routes.py              |       58 |        0 |    100% |           |
| app/sep/plugins/checksums/deps.py                 |      130 |       63 |     52% |65-76, 90-128, 156, 158, 264-266, 280, 363-368, 384-411, 424-451, 462, 492 |
| app/sep/plugins/checksums/models.py               |       33 |        0 |    100% |           |
| app/sep/plugins/checksums/routes.py               |       74 |       33 |     55% |63-64, 148-198, 218-226, 241-247, 263-264 |
| app/sep/plugins/dipper/constants.py               |       10 |        0 |    100% |           |
| app/sep/plugins/dipper/deps.py                    |      107 |       75 |     30% |69-77, 88, 104-109, 123-124, 140-149, 175-204, 215-223, 239-254, 274-282, 294-301, 327-335 |
| app/sep/plugins/dipper/models.py                  |        6 |        0 |    100% |           |
| app/sep/plugins/dipper/routes.py                  |       66 |       44 |     33% |74-190, 207-212 |
| app/sep/plugins/inventory/deps.py                 |       52 |        7 |     87% |   200-224 |
| app/sep/plugins/inventory/routes.py               |      125 |        0 |    100% |           |
| app/sep/plugins/inventory/sync.py                 |       30 |        0 |    100% |           |
| app/sep/plugins/report/deps.py                    |       28 |        0 |    100% |           |
| app/sep/plugins/report/models.py                  |      111 |        0 |    100% |           |
| app/sep/plugins/report/routes.py                  |       39 |        0 |    100% |           |
| app/sep/plugins/report/service.py                 |      378 |       16 |     96% |126, 130, 331, 345-346, 407, 444-445, 447, 451, 553, 558, 566, 575, 638, 645 |
| app/sep/plugins/snippets/deps.py                  |       68 |       39 |     43% |60-63, 82-93, 102-105, 131-133, 162-164, 193-195, 213-222, 242-258, 277-282 |
| app/sep/plugins/snippets/routes.py                |       69 |       38 |     45% |61-63, 81-116, 126-128, 139-141, 149-151, 159-164, 179-194 |
| app/sep/plugins/tasks/deps.py                     |        5 |        0 |    100% |           |
| app/sep/plugins/tasks/models.py                   |        6 |        0 |    100% |           |
| app/sep/plugins/tasks/routes.py                   |       56 |        0 |    100% |           |
| app/sep/routes/artifacts.py                       |       31 |        1 |     97% |        66 |
| app/sep/routes/download\_files.py                 |       37 |        0 |    100% |           |
| app/sep/routes/execution\_events.py               |       14 |        0 |    100% |           |
| app/sep/routes/periodic\_tasks.py                 |       28 |        0 |    100% |           |
| app/sep/routes/stop\_task.py                      |       19 |        0 |    100% |           |
| app/sep/routes/stream\_logs.py                    |       78 |       29 |     63% |86, 91-98, 109-132, 185-207 |
| app/sep/snippets/config.py                        |      128 |       20 |     84% |122, 194-203, 215, 265, 347-352, 433, 444, 460-463 |
| app/sep/snippets/crud.py                          |       15 |        0 |    100% |           |
| app/sep/snippets/forms.py                         |      242 |       10 |     96% |179, 670-673, 829, 831, 842, 950, 957 |
| app/sep/snippets/models/meta.py                   |      139 |        1 |     99% |       250 |
| app/sep/snippets/models/snippet.py                |      365 |       40 |     89% |226, 273, 276-277, 343-350, 358, 373-384, 396-397, 590, 630-642, 723-725, 799-801, 876, 881, 907-918 |
| app/sep/snippets/utils.py                         |       28 |        0 |    100% |           |
| app/sep/sync/exceptions.py                        |       25 |        0 |    100% |           |
| app/sep/sync/models.py                            |      348 |       60 |     83% |75-84, 98-100, 119, 267-269, 330, 390-391, 424, 478-480, 537, 567, 583, 603-607, 708, 722, 742-743, 823, 837, 859-860, 941, 954, 978-980, 1052, 1065, 1085-1086, 1161, 1305-1307, 1316, 1361-1362, 1365, 1371-1373, 1378-1384, 1388 |
| app/sep/sync/syncers/mysql/payload.py             |      175 |       47 |     73% |240-244, 249-254, 267-273, 277-300, 373, 394-402, 421 |
| app/sep/sync/syncers/mysql/syncer.py              |      243 |       10 |     96% |114, 368, 624, 646, 664, 753-762 |
| app/sep/sync/syncers/pmm.py                       |       93 |       20 |     78% |83-87, 107-110, 121, 176-184, 232, 234, 236-252, 344 |
| app/sep/tasks.py                                  |       31 |        0 |    100% |           |
| app/sep/utils/decorators.py                       |       10 |        0 |    100% |           |
| app/sep/utils/jinja.py                            |       60 |       10 |     83% |103, 122, 133-138, 169-170 |
| app/sep/utils/static.py                           |       16 |        0 |    100% |           |
| app/tasks/anonymizer/anonymize.py                 |       50 |        0 |    100% |           |
| app/tasks/anonymizer/config.py                    |       27 |        1 |     96% |        68 |
| app/tasks/anonymizer/entities.py                  |       28 |        0 |    100% |           |
| app/tasks/celery.py                               |      201 |       23 |     89% |139-163, 169, 179-181, 203-205, 524, 547-548 |
| app/tasks/config.py                               |       21 |        0 |    100% |           |
| app/tasks/connectivity/constants.py               |        4 |        0 |    100% |           |
| app/tasks/connectivity/models.py                  |       11 |        0 |    100% |           |
| app/tasks/connectivity/payload.py                 |       54 |        1 |     98% |       133 |
| app/tasks/connectivity/routes.py                  |       15 |        0 |    100% |           |
| app/tasks/connectivity/service.py                 |      100 |        2 |     98% |  177, 343 |
| app/tasks/crud.py                                 |      153 |        1 |     99% |       124 |
| app/tasks/db/engine.py                            |        8 |        0 |    100% |           |
| app/tasks/db/seed.py                              |       57 |       25 |     56% |428-486, 515 |
| app/tasks/deps.py                                 |       91 |        3 |     97% |     60-62 |
| app/tasks/execution/exceptions.py                 |        8 |        0 |    100% |           |
| app/tasks/execution/executors/celery/models.py    |       78 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/exceptions.py |        4 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/models.py     |      616 |      150 |     76% |100-102, 109, 126-129, 149, 192, 368, 637, 643, 776, 778, 903, 945-975, 996-1010, 1036-1046, 1067-1070, 1149-1151, 1177-1178, 1215-1216, 1250-1251, 1418-1467, 1475-1476, 1480, 1504-1548, 1605-1606, 1678-1679, 1697-1749 |
| app/tasks/execution/models.py                     |       62 |        1 |     98% |       227 |
| app/tasks/execution/utils.py                      |       26 |        0 |    100% |           |
| app/tasks/logs/log\_reader.py                     |       51 |        0 |    100% |           |
| app/tasks/logs/log\_writer.py                     |      123 |        8 |     93% |116, 226-227, 349, 353, 357, 537, 543 |
| app/tasks/main.py                                 |       57 |       11 |     81% |56-59, 80-81, 130-131, 138-142 |
| app/tasks/models.py                               |      279 |        3 |     99% |586, 1019-1020 |
| app/tasks/periodic/config.py                      |       12 |        0 |    100% |           |
| app/tasks/periodic/crud.py                        |       26 |        0 |    100% |           |
| app/tasks/periodic/deps.py                        |       11 |        0 |    100% |           |
| app/tasks/periodic/models.py                      |      101 |        5 |     95% |196, 231, 283, 299, 368 |
| app/tasks/periodic/routes.py                      |       38 |        3 |     92% | 62-66, 97 |
| app/tasks/routes.py                               |      182 |       19 |     90% |119-123, 180, 201-208, 240, 289-297, 302-303, 492, 505-506 |
| **TOTAL**                                         | **12449** | **1914** | **85%** |           |


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