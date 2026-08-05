# Repository Coverage



| Name                                                                                                                  |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|---------------------------------------------------------------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| app/api/deps.py                                                                                                       |       48 |        0 |        8 |        0 |    100% |           |
| app/api/main.py                                                                                                       |        6 |        0 |        0 |        0 |    100% |           |
| app/api/routes/config.py                                                                                              |        9 |        0 |        0 |        0 |    100% |           |
| app/api/routes/oauth.py                                                                                               |       75 |        0 |       14 |        0 |    100% |           |
| app/api/routes/users.py                                                                                               |       21 |        0 |        4 |        0 |    100% |           |
| app/celery.py                                                                                                         |       34 |        4 |        2 |        0 |     89% | 51, 57-59 |
| app/core/alerts/config.py                                                                                             |       43 |        0 |        4 |        0 |    100% |           |
| app/core/alerts/models.py                                                                                             |       57 |        0 |       10 |        0 |    100% |           |
| app/core/alerts/providers/pagerduty.py                                                                                |       35 |        1 |        0 |        0 |     97% |       110 |
| app/core/auth/base.py                                                                                                 |       14 |        2 |        0 |        0 |     86% |    63, 81 |
| app/core/auth/config.py                                                                                               |       79 |        2 |       22 |        2 |     96% |  118, 161 |
| app/core/auth/exceptions.py                                                                                           |       11 |        0 |        0 |        0 |    100% |           |
| app/core/auth/models.py                                                                                               |       70 |        0 |        0 |        0 |    100% |           |
| app/core/auth/providers/casdoor/models.py                                                                             |       84 |        5 |       10 |        0 |     90% |   194-200 |
| app/core/auth/providers/casdoor/provider.py                                                                           |       14 |        0 |        0 |        0 |    100% |           |
| app/core/auth/providers/casdoor/sdk.py                                                                                |      123 |       53 |       26 |        3 |     53% |51, 106-107, 118, 145-\>147, 161-170, 189-190, 209-216, 240-260, 267-268, 286-295, 309-310, 342-\>341, 360-365, 373-374, 387, 397-401, 411-415 |
| app/core/auth/providers/grafana/models.py                                                                             |      140 |        3 |       18 |        1 |     97% |284, 483-484 |
| app/core/auth/providers/grafana/provider.py                                                                           |       25 |        0 |        4 |        0 |    100% |           |
| app/core/auth/providers/grafana/sdk.py                                                                                |       54 |        0 |        6 |        0 |    100% |           |
| app/core/auth/utils.py                                                                                                |        6 |        1 |        0 |        0 |     83% |        35 |
| app/core/celery/config.py                                                                                             |       33 |        0 |        2 |        0 |    100% |           |
| app/core/celery/crud.py                                                                                               |       26 |        2 |        4 |        1 |     90% |     91-97 |
| app/core/celery/db.py                                                                                                 |        8 |        0 |        0 |        0 |    100% |           |
| app/core/celery/deps.py                                                                                               |       10 |        0 |        0 |        0 |    100% |           |
| app/core/celery/models.py                                                                                             |       36 |        2 |        6 |        2 |     90% |   72, 135 |
| app/core/celery/utils.py                                                                                              |       31 |        2 |       10 |        2 |     90% |   92, 120 |
| app/core/config.py                                                                                                    |      219 |        5 |       46 |        5 |     96% |225-\>exit, 455, 543, 619, 632, 670-\>672, 675 |
| app/core/db/config.py                                                                                                 |       25 |        0 |        2 |        0 |    100% |           |
| app/core/db/crud.py                                                                                                   |      297 |       21 |       86 |        9 |     91% |197, 252-\>254, 254-\>256, 256-\>258, 265-\>281, 316-333, 351, 356, 373, 487-490, 904, 908, 1174-1175 |
| app/core/db/list\_query.py                                                                                            |       77 |        0 |       24 |        0 |    100% |           |
| app/core/db/models.py                                                                                                 |       14 |        0 |        0 |        0 |    100% |           |
| app/core/db/sql\_types.py                                                                                             |       37 |        0 |       12 |        0 |    100% |           |
| app/core/db/utils.py                                                                                                  |       88 |        5 |       26 |        5 |     91% |105, 292, 321, 324, 342 |
| app/core/exceptions.py                                                                                                |       32 |        0 |        0 |        0 |    100% |           |
| app/core/health.py                                                                                                    |       18 |        0 |        0 |        0 |    100% |           |
| app/core/log.py                                                                                                       |       21 |        0 |        8 |        0 |    100% |           |
| app/core/middleware/log\_context.py                                                                                   |       26 |        0 |        2 |        0 |    100% |           |
| app/core/middleware/security\_headers.py                                                                              |      105 |        0 |       20 |        1 |     99% |221-\>exit |
| app/core/models.py                                                                                                    |       20 |        0 |        2 |        0 |    100% |           |
| app/core/pagination/deps.py                                                                                           |       17 |        0 |        2 |        0 |    100% |           |
| app/core/pagination/models.py                                                                                         |       78 |        0 |       20 |        0 |    100% |           |
| app/core/pmm.py                                                                                                       |       51 |        1 |       10 |        1 |     97% |        53 |
| app/core/requests/connectivity.py                                                                                     |       29 |        0 |        8 |        0 |    100% |           |
| app/core/requests/registry.py                                                                                         |       64 |        5 |       22 |        5 |     88% |101, 112, 152, 163, 173 |
| app/core/requests/remote\_api.py                                                                                      |      285 |        2 |       60 |        3 |     99% |247, 266, 691-\>690 |
| app/core/security.py                                                                                                  |       14 |        0 |        4 |        0 |    100% |           |
| app/core/settings\_override/api/export.py                                                                             |       10 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/api/models.py                                                                             |       20 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/api/routes.py                                                                             |      281 |       31 |       92 |        8 |     87% |317, 431, 455, 585-592, 720, 748-758, 791-799, 807, 933, 963-964, 1020, 1022-1023, 1098, 1104, 1106, 1129, 1291-\>1309, 1296-1308 |
| app/core/settings\_override/cache.py                                                                                  |      118 |       13 |       46 |        6 |     86% |192-197, 210-215, 297, 360, 401, 405-412 |
| app/core/settings\_override/constants.py                                                                              |        1 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/lifecycle.py                                                                              |       69 |        1 |       14 |        0 |     99% |       267 |
| app/core/settings\_override/manager.py                                                                                |        5 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/models.py                                                                                 |       24 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/policy.py                                                                                 |       30 |        0 |        6 |        0 |    100% |           |
| app/core/settings\_override/proxy.py                                                                                  |       22 |        0 |        2 |        0 |    100% |           |
| app/core/settings\_override/registry.py                                                                               |      641 |       50 |      330 |       32 |     90% |764, 823, 966, 1019, 1053, 1068, 1094, 1126, 1281, 1334-\>1338, 1341, 1401-1402, 1406, 1407-\>1393, 1408-\>1407, 1438, 1443, 1480, 1509, 1528, 1627, 1632, 1658, 1686-\>1681, 1709-1715, 1746, 1749, 1776-1777, 1791-1801, 1828-1831, 1840-1843, 1847-1850, 1976 |
| app/core/settings\_override/worker.py                                                                                 |       25 |        0 |        6 |        0 |    100% |           |
| app/core/utils/async\_run.py                                                                                          |       13 |        0 |        0 |        0 |    100% |           |
| app/core/utils/cache.py                                                                                               |       92 |        5 |       18 |        4 |     90% |60-62, 147-\>153, 151, 186-\>191, 223 |
| app/core/utils/cli\_args.py                                                                                           |       12 |        0 |        0 |        0 |    100% |           |
| app/core/utils/date\_time.py                                                                                          |        8 |        0 |        2 |        0 |    100% |           |
| app/core/utils/dict.py                                                                                                |       27 |        4 |       10 |        0 |     84% |   159-162 |
| app/core/utils/fields.py                                                                                              |      216 |        8 |       28 |        6 |     94% |170, 242-243, 410, 414, 574, 622, 645 |
| app/core/utils/imports.py                                                                                             |       28 |        0 |        8 |        0 |    100% |           |
| app/core/utils/iterators.py                                                                                           |       18 |        0 |        6 |        0 |    100% |           |
| app/core/utils/json\_pointer.py                                                                                       |       41 |        0 |       22 |        0 |    100% |           |
| app/core/utils/lazy.py                                                                                                |       31 |        0 |        4 |        0 |    100% |           |
| app/core/utils/openapi.py                                                                                             |      246 |        5 |      120 |        7 |     96% |141, 513, 515-\>514, 520-521, 564-\>566, 583-\>582, 600 |
| app/core/utils/path.py                                                                                                |       40 |        0 |       14 |        0 |    100% |           |
| app/core/utils/pydantic.py                                                                                            |       63 |        0 |       22 |        0 |    100% |           |
| app/core/utils/serialization.py                                                                                       |        7 |        0 |        0 |        0 |    100% |           |
| app/core/utils/strings.py                                                                                             |       24 |        3 |        4 |        1 |     79% |     64-69 |
| app/inventory/config.py                                                                                               |       12 |        0 |        0 |        0 |    100% |           |
| app/inventory/constants.py                                                                                            |        2 |        0 |        0 |        0 |    100% |           |
| app/inventory/crud.py                                                                                                 |       30 |        0 |        0 |        0 |    100% |           |
| app/inventory/db.py                                                                                                   |        6 |        0 |        0 |        0 |    100% |           |
| app/inventory/deps.py                                                                                                 |       29 |        3 |        0 |        0 |     90% |     39-41 |
| app/inventory/main.py                                                                                                 |       44 |        8 |        2 |        1 |     80% |52, 99-100, 131-132, 136-140 |
| app/inventory/models.py                                                                                               |       92 |        0 |        4 |        0 |    100% |           |
| app/inventory/routes/nodes.py                                                                                         |       52 |        2 |        4 |        0 |     93% |  140, 142 |
| app/inventory/routes/schemas.py                                                                                       |       34 |        0 |        0 |        0 |    100% |           |
| app/inventory/routes/services.py                                                                                      |       48 |        3 |        4 |        0 |     87% |131, 133, 167 |
| app/inventory/routes/tables.py                                                                                        |       26 |        0 |        0 |        0 |    100% |           |
| app/inventory/settings/routes.py                                                                                      |       10 |        0 |        0 |        0 |    100% |           |
| app/main.py                                                                                                           |       81 |       25 |        4 |        1 |     67% |191-195, 199-253 |
| app/sep/api/constants.py                                                                                              |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/api/host\_resolution.py                                                                                       |        9 |        0 |        4 |        0 |    100% |           |
| app/sep/api/models.py                                                                                                 |       13 |        0 |        0 |        0 |    100% |           |
| app/sep/api/openapi.py                                                                                                |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/api/proxy.py                                                                                                  |       16 |        0 |        2 |        0 |    100% |           |
| app/sep/api/router.py                                                                                                 |       38 |        0 |        4 |        0 |    100% |           |
| app/sep/api/routes/app\_info.py                                                                                       |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/app\_state.py                                                                                      |       44 |       12 |       10 |        2 |     59% |180, 186, 188-195, 202, 208-209, 237-238, 243-244, 251 |
| app/sep/api/routes/apps.py                                                                                            |       22 |        3 |        2 |        1 |     83% |87, 107-108 |
| app/sep/api/routes/connectivity\_check.py                                                                             |       55 |        0 |       18 |        0 |    100% |           |
| app/sep/api/routes/dashboard.py                                                                                       |       35 |        0 |        6 |        0 |    100% |           |
| app/sep/api/routes/hosts.py                                                                                           |       22 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/periodic\_tasks.py                                                                                 |       23 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/schemas.py                                                                                         |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/services.py                                                                                        |       17 |        0 |        2 |        0 |    100% |           |
| app/sep/api/routes/settings.py                                                                                        |      130 |        6 |       50 |        3 |     94% |133, 138, 293-295, 323 |
| app/sep/api/routes/task\_history.py                                                                                   |       26 |        0 |        4 |        0 |    100% |           |
| app/sep/api/routes/task\_stats.py                                                                                     |       13 |        0 |        0 |        0 |    100% |           |
| app/sep/api/task\_history\_merge.py                                                                                   |       55 |        4 |       16 |        3 |     90% |57, 61-62, 113, 115-\>117 |
| app/sep/app\_drain.py                                                                                                 |       83 |        2 |       14 |        2 |     96% |137-\>139, 206, 212 |
| app/sep/apps/alert\_troubleshooting/api\_routes.py                                                                    |       23 |        4 |        2 |        0 |     76% |64-65, 73-80 |
| app/sep/apps/alert\_troubleshooting/app.py                                                                            |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alert\_troubleshooting/deps.py                                                                           |      135 |       15 |       46 |        3 |     89% |122, 124-\>126, 237, 280, 364, 388-394, 418-420, 444-447, 474 |
| app/sep/apps/alert\_troubleshooting/models.py                                                                         |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alert\_troubleshooting/routes.py                                                                         |       66 |        4 |       16 |        3 |     91% |61-\>57, 69-\>57, 138-142, 193-194 |
| app/sep/apps/alert\_troubleshooting/schema.py                                                                         |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/api\_routes.py                                                                                    |      120 |       16 |       16 |        0 |     85% |181, 197-200, 244-254 |
| app/sep/apps/alerts/app.py                                                                                            |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/app\_owned\_settings.py                                                                           |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/celery.py                                                                                         |       46 |        1 |       10 |        0 |     98% |        39 |
| app/sep/apps/alerts/config.py                                                                                         |       14 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/crud.py                                                                                           |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/deps.py                                                                                           |       80 |        0 |       16 |        0 |    100% |           |
| app/sep/apps/alerts/loader.py                                                                                         |       22 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/alerts/migrations/versions/2026\_04\_20\_1817-d21ad387df7a\_create\_alert\_backup\_table.py              |       14 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/alerts/models.py                                                                                         |       44 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/restore.py                                                                                        |       95 |        0 |       26 |        0 |    100% |           |
| app/sep/apps/alerts/routes.py                                                                                         |      112 |       12 |       16 |        1 |     90% |101-103, 290-291, 331-349 |
| app/sep/apps/alters/api\_routes.py                                                                                    |       38 |        3 |        0 |        0 |     92% |82, 140-145 |
| app/sep/apps/alters/app.py                                                                                            |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alters/deps.py                                                                                           |      256 |       11 |       64 |       10 |     93% |218, 268-\>280, 274-\>273, 278-\>273, 484, 551-552, 610, 693, 716-717, 840, 851, 853, 892-\>896 |
| app/sep/apps/alters/form\_backfill.py                                                                                 |       32 |        1 |       10 |        1 |     95% |       100 |
| app/sep/apps/alters/models.py                                                                                         |       49 |        1 |        6 |        1 |     96% |       121 |
| app/sep/apps/alters/pre\_checks.py                                                                                    |      236 |      236 |       72 |        0 |      0% |    27-638 |
| app/sep/apps/alters/routes.py                                                                                         |      101 |        0 |        4 |        0 |    100% |           |
| app/sep/apps/alters/schema.py                                                                                         |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alters/spec.py                                                                                           |       42 |        1 |       18 |        1 |     97% |        52 |
| app/sep/apps/alters/views.py                                                                                          |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/archives/alerts.py                                                                                       |      130 |        6 |       40 |        4 |     94% |178, 213, 255, 338-339, 349, 371-\>376 |
| app/sep/apps/archives/app.py                                                                                          |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/archives/constants.py                                                                                    |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/archives/deps.py                                                                                         |       90 |        3 |       22 |        4 |     94% |183, 191, 193, 259-\>269 |
| app/sep/apps/archives/form\_backfill.py                                                                               |      141 |       16 |       72 |       16 |     85% |41, 54, 57, 66-67, 69, 73, 80, 100, 116, 165-\>167, 179-\>182, 184, 194, 224, 228, 236, 278 |
| app/sep/apps/archives/models.py                                                                                       |       76 |        0 |        4 |        0 |    100% |           |
| app/sep/apps/archives/payload                                                                                         |      195 |      135 |       60 |        2 |     28% |44-235, 240-246, 295, 300-309, 385-400, 405-409, 413 |
| app/sep/apps/archives/routes.py                                                                                       |       91 |        3 |       16 |        5 |     93% |137-\>139, 144, 146, 148, 151-\>153 |
| app/sep/apps/archives/spec.py                                                                                         |       55 |        2 |       24 |        4 |     92% |106, 133, 156-\>164, 178-\>185 |
| app/sep/apps/archives/views.py                                                                                        |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/api\_routes.py                                                                                       |      207 |       47 |       38 |        3 |     75% |178-\>188, 228, 243, 268, 342-343, 347-353, 416-429, 431-447, 456, 458-474, 494-496, 623-\>630, 624, 680-686, 688-691, 709, 727, 766 |
| app/sep/apps/atw/app.py                                                                                               |       12 |        1 |        2 |        1 |     86% |        47 |
| app/sep/apps/atw/batch.py                                                                                             |       77 |        0 |        8 |        0 |    100% |           |
| app/sep/apps/atw/categories.py                                                                                        |       34 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/atw/celery.py                                                                                            |       18 |        5 |        2 |        0 |     65% | 42, 54-57 |
| app/sep/apps/atw/config.py                                                                                            |       15 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/crud.py                                                                                              |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/deps.py                                                                                              |       29 |        0 |        8 |        0 |    100% |           |
| app/sep/apps/atw/migrations/versions/2026\_07\_20\_1238-b82887dfe93d\_create\_atw\_incident\_tables.py                |       24 |        7 |        8 |        2 |     59% |40-\>55, 55-\>exit, 85-94 |
| app/sep/apps/atw/migrations/versions/2026\_07\_24\_1100-c93998e0fa14\_create\_atw\_send\_log\_table.py                |       20 |        5 |        4 |        1 |     67% |40-\>exit, 81-87 |
| app/sep/apps/atw/migrations/versions/2026\_07\_30\_1200-447ee0172734\_add\_atw\_incident\_closed\_at.py               |       25 |        2 |        8 |        4 |     82% |41, 43-\>exit, 55, 57-\>exit |
| app/sep/apps/atw/models.py                                                                                            |       58 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/schema.py                                                                                            |       13 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/atw/send.py                                                                                              |      255 |        7 |       48 |        0 |     98% |107, 163, 175, 305, 474, 745-746 |
| app/sep/apps/backup\_mongo/api\_routes.py                                                                             |       30 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/app.py                                                                                     |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/deps.py                                                                                    |      126 |       17 |       18 |        0 |     83% |265-284, 483-485 |
| app/sep/apps/backup\_mongo/models.py                                                                                  |      239 |        0 |       42 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/pbm\_config\_payload                                                                       |       89 |       64 |       28 |        5 |     29% |21-\>30, 23-\>30, 25-26, 32-36, 52-\>54, 56-60, 70-173 |
| app/sep/apps/backup\_mongo/pbm\_creds\_common.py                                                                      |      159 |        3 |       32 |        1 |     98% |83-\>92, 147-149 |
| app/sep/apps/backup\_mongo/pbm\_incremental\_payload                                                                  |      147 |       29 |       52 |        6 |     82% |26-27, 33-37, 53-\>55, 57-61, 74-88, 103-105, 156, 168-172, 182-191 |
| app/sep/apps/backup\_mongo/pbm\_logical\_payload                                                                      |      185 |       24 |       50 |        3 |     89% |59-\>61, 63-67, 80-94, 181, 246-247, 339-340, 417-423 |
| app/sep/apps/backup\_mongo/pbm\_physical\_payload                                                                     |      174 |       24 |       44 |        3 |     88% |59-\>61, 63-67, 80-94, 161, 226-227, 319-320, 394-400 |
| app/sep/apps/backup\_mongo/pbm\_snapshot\_payload                                                                     |       68 |       11 |        6 |        2 |     82% |31-40, 58-59, 122, 131-132 |
| app/sep/apps/backup\_mongo/pbm\_status\_payload                                                                       |       59 |       34 |       16 |        5 |     45% |21-\>30, 23-\>30, 25-26, 32-36, 52-\>54, 56-60, 70-107 |
| app/sep/apps/backup\_mongo/restore/api\_routes.py                                                                     |       34 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/app.py                                                                             |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/deps.py                                                                            |      203 |       37 |       40 |        3 |     75% |151-172, 202, 264-265, 297, 579-595, 610, 781-792 |
| app/sep/apps/backup\_mongo/restore/models.py                                                                          |      159 |        7 |       22 |        5 |     93% |79-81, 83, 86-90, 302-\>306, 340-\>342, 640 |
| app/sep/apps/backup\_mongo/restore/pbm\_force\_resync\_payload                                                        |       55 |       30 |       16 |        5 |     48% |21-\>30, 23-\>30, 25-26, 32-36, 52-\>54, 56-60, 70-103 |
| app/sep/apps/backup\_mongo/restore/pbm\_list\_payload                                                                 |       55 |       30 |       16 |        5 |     48% |21-\>30, 23-\>30, 25-26, 32-36, 52-\>54, 56-60, 70-103 |
| app/sep/apps/backup\_mongo/restore/pbm\_logical\_restore\_payload                                                     |       82 |       23 |       24 |        5 |     74% |21-\>30, 23-\>30, 25-26, 32-36, 56-60, 73-87, 118-124, 163 |
| app/sep/apps/backup\_mongo/restore/pbm\_physical\_restore\_payload                                                    |       79 |       36 |       22 |        6 |     54% |21-\>30, 23-\>30, 25-26, 32-36, 56-60, 73-87, 106-124, 140-\>143, 152-160 |
| app/sep/apps/backup\_mongo/restore/pbm\_restore\_config\_payload                                                      |      129 |       64 |       54 |       10 |     48% |21-\>30, 23-\>30, 25-26, 32-36, 56-60, 73-87, 116-117, 132-133, 137-139, 140-\>146, 143-144, 149-150, 158-198 |
| app/sep/apps/backup\_mongo/restore/routes.py                                                                          |      140 |       35 |       18 |        9 |     72% |71-72, 80-81, 106-111, 121-126, 143-144, 147-152, 196, 214, 245-246, 252, 289-290, 295-296, 321-322, 352-361, 400-402 |
| app/sep/apps/backup\_mongo/restore/schema.py                                                                          |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/spec.py                                                                            |       31 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/views.py                                                                           |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/routes.py                                                                                  |       81 |       10 |        8 |        1 |     88% |66, 105-106, 209-218, 232-235 |
| app/sep/apps/backup\_mongo/schema.py                                                                                  |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/spec.py                                                                                    |       49 |        2 |       22 |        3 |     93% |85-\>88, 129, 134 |
| app/sep/apps/backup\_mongo/views.py                                                                                   |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/app.py                                                                                        |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/deps.py                                                                                       |       74 |        6 |       10 |        1 |     92% |109-110, 113, 147-149 |
| app/sep/apps/backup\_pg/form\_backfill.py                                                                             |       46 |        4 |       16 |        4 |     87% |44-\>57, 47-48, 49-\>57, 51-\>57, 53-\>57, 85-86 |
| app/sep/apps/backup\_pg/models.py                                                                                     |       48 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/routes.py                                                                                     |       63 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/spec.py                                                                                       |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/views.py                                                                                      |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/checksums/app.py                                                                                         |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/checksums/deps.py                                                                                        |       72 |        9 |       14 |        0 |     87% |268-270, 287-292 |
| app/sep/apps/checksums/form\_backfill.py                                                                              |       48 |        4 |       24 |        5 |     88% |55, 63, 70, 91, 109-\>108 |
| app/sep/apps/checksums/models.py                                                                                      |       65 |        4 |       16 |        4 |     90% |52, 54, 57, 299 |
| app/sep/apps/checksums/routes.py                                                                                      |       66 |        7 |        0 |        0 |     89% |142-144, 184-192, 229-230 |
| app/sep/apps/checksums/spec.py                                                                                        |       68 |        0 |       26 |        2 |     98% |115-\>123, 190-\>192 |
| app/sep/apps/checksums/views.py                                                                                       |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/api\_routes.py                                                                                    |       66 |        4 |        4 |        1 |     93% |82-83, 139-140 |
| app/sep/apps/dipper/app.py                                                                                            |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/constants.py                                                                                      |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/deps.py                                                                                           |      173 |       40 |       48 |        9 |     74% |128-130, 151-152, 170-175, 189-190, 237-266, 301-\>307, 329-332, 333-\>340, 363, 364-\>366, 452, 454, 456, 539, 578 |
| app/sep/apps/dipper/models.py                                                                                         |       17 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/payloads/pcs-collect-pmm-mysql.py                                                                 |      304 |      260 |      122 |        3 |     11% |   266-881 |
| app/sep/apps/dipper/payloads/pcs-collect-pmm-valkey.py                                                                |      226 |       41 |       82 |       10 |     78% |248, 251, 253-\>256, 256-\>259, 275-345, 357, 425, 441-442, 474-\>479, 482-\>550, 655-659 |
| app/sep/apps/dipper/routes.py                                                                                         |       64 |       38 |       12 |        1 |     36% |    90-195 |
| app/sep/apps/dipper/schema.py                                                                                         |       35 |        1 |       10 |        1 |     96% |       236 |
| app/sep/apps/framework/api.py                                                                                         |      321 |       10 |      124 |        8 |     96% |137-\>135, 192-197, 719, 726, 854, 860, 865, 871, 886, 1293 |
| app/sep/apps/framework/apps.py                                                                                        |      318 |        8 |      124 |        7 |     97% |135, 516, 680, 696, 713, 773, 787, 794 |
| app/sep/apps/framework/base.py                                                                                        |       49 |        2 |        6 |        2 |     93% |  179, 186 |
| app/sep/apps/framework/cascade.py                                                                                     |      189 |        0 |       62 |        2 |     99% |133-\>135, 149-\>151 |
| app/sep/apps/framework/conformance.py                                                                                 |      101 |        9 |       52 |        7 |     88% |68, 173, 209-213, 272, 285, 289, 337 |
| app/sep/apps/framework/connectivity.py                                                                                |       25 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/framework/deprecation.py                                                                                 |       22 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/framework/deps.py                                                                                        |       15 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/framework/form\_backfill.py                                                                              |      179 |       34 |       30 |        4 |     80% |128, 133, 138, 143, 148, 266-272, 275-280, 297-303, 306, 390-\>397, 420-459, 548 |
| app/sep/apps/framework/form\_backfill\_guards.py                                                                      |       10 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/framework/form\_backfill\_inventory.py                                                                   |      139 |       12 |       52 |       12 |     87% |73, 78-\>exit, 146, 149, 153, 166-\>144, 198, 201-\>214, 218, 251, 269, 282-283, 292-297, 319-\>325 |
| app/sep/apps/framework/form\_backfill\_registry.py                                                                    |       35 |        0 |       14 |        0 |    100% |           |
| app/sep/apps/framework/form\_dsl/conformance.py                                                                       |       46 |        9 |       18 |        3 |     75% |65, 69, 85-93 |
| app/sep/apps/framework/form\_dsl/derivation.py                                                                        |      350 |       22 |      178 |       23 |     91% |258, 275, 451, 467, 474, 480-\>476, 489, 499-\>505, 502-504, 518-\>520, 523, 525-\>520, 527, 544, 550, 565, 568, 576, 582-583, 585, 636, 642, 836 |
| app/sep/apps/framework/form\_dsl/markers.py                                                                           |      121 |        1 |       14 |        1 |     99% |       189 |
| app/sep/apps/framework/form\_dsl/model.py                                                                             |       17 |        1 |        2 |        1 |     89% |        70 |
| app/sep/apps/framework/form\_dsl/pt\_toolkit.py                                                                       |       56 |        0 |       26 |        0 |    100% |           |
| app/sep/apps/framework/registry.py                                                                                    |      177 |        4 |       92 |        4 |     97% |410, 416, 418, 437 |
| app/sep/apps/framework/responses.py                                                                                   |       79 |        0 |       12 |        0 |    100% |           |
| app/sep/apps/framework/rules.py                                                                                       |      538 |        7 |      130 |        5 |     98% |323, 328, 333, 545, 861, 1348, 1368 |
| app/sep/apps/framework/scaffold.py                                                                                    |      429 |       29 |      150 |       20 |     91% |281, 292, 304, 421, 516, 519, 539-\>546, 542, 593-595, 629, 670, 674, 874, 1103-1106, 1132, 1134, 1148-1151, 1177, 1182-1185, 1204, 1244 |
| app/sep/apps/framework/schema.py                                                                                      |      393 |        2 |      114 |        2 |     99% |1311, 1763 |
| app/sep/apps/framework/script\_helpers.py                                                                             |       41 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/framework/script\_source.py                                                                              |       65 |        0 |       14 |        0 |    100% |           |
| app/sep/apps/framework/spec.py                                                                                        |      146 |        0 |       68 |        0 |    100% |           |
| app/sep/apps/framework/task\_status.py                                                                                |       44 |        0 |       14 |        0 |    100% |           |
| app/sep/apps/inventory/api\_routes.py                                                                                 |       74 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/app.py                                                                                         |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/connectivity.py                                                                                |       42 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/inventory/constants.py                                                                                   |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/deps.py                                                                                        |      138 |       13 |       54 |        3 |     90% |276-300, 412-417, 460, 467 |
| app/sep/apps/inventory/models.py                                                                                      |       29 |        1 |        8 |        1 |     95% |        92 |
| app/sep/apps/inventory/routes.py                                                                                      |      150 |        0 |       10 |        0 |    100% |           |
| app/sep/apps/inventory/schema.py                                                                                      |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/sync.py                                                                                        |       30 |        0 |       12 |        0 |    100% |           |
| app/sep/apps/labels.py                                                                                                |        1 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/api\_routes.py                                                                            |       18 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/app.py                                                                                    |       15 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/backup\_source\_choices.py                                                                |       62 |       11 |       24 |        1 |     77% |   143-153 |
| app/sep/apps/mysql\_backups/crud.py                                                                                   |       10 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/deps.py                                                                                   |       80 |        1 |       12 |        2 |     97% |104, 244-\>247 |
| app/sep/apps/mysql\_backups/form\_backfill.py                                                                         |       55 |        6 |       22 |        8 |     82% |60-\>82, 63-64, 65-\>82, 67-\>82, 69-\>82, 73-\>82, 76, 80-\>74, 106-107, 117 |
| app/sep/apps/mysql\_backups/forms.py                                                                                  |      186 |        2 |       14 |        2 |     98% |  632, 647 |
| app/sep/apps/mysql\_backups/migrations/versions/2026\_07\_29\_1200-f0a1b2c3d4e5\_create\_mysql\_backup\_run\_table.py |       22 |        6 |        4 |        1 |     65% |40-\>exit, 89-98 |
| app/sep/apps/mysql\_backups/models.py                                                                                 |       45 |        0 |        4 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/mydumper\_payload                                                                         |     1173 |     1166 |      416 |        0 |      1% |8-39, 43-406, 435-2350 |
| app/sep/apps/mysql\_backups/recorder.py                                                                               |       36 |        0 |        8 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/restore/app.py                                                                            |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/restore/deps.py                                                                           |       95 |       11 |       20 |        2 |     89% |183-184, 188, 193, 196-197, 282-287 |
| app/sep/apps/mysql\_backups/restore/form\_backfill.py                                                                 |       55 |        3 |       18 |        1 |     95% |127-128, 141 |
| app/sep/apps/mysql\_backups/restore/models.py                                                                         |      141 |        2 |       14 |        2 |     97% |   52, 477 |
| app/sep/apps/mysql\_backups/restore/routes.py                                                                         |       66 |        8 |        0 |        0 |     88% |147-148, 177-186, 223-225 |
| app/sep/apps/mysql\_backups/restore/spec.py                                                                           |       34 |        1 |        8 |        1 |     95% |       103 |
| app/sep/apps/mysql\_backups/restore/views.py                                                                          |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/restore/xtrabackup\_payload                                                               |     1584 |     1568 |      604 |        4 |      1% |2-1786, 1800, 1801-\>1798, 1803-2378, 2391-2598 |
| app/sep/apps/mysql\_backups/routes.py                                                                                 |       75 |        3 |        0 |        0 |     96% |74, 182-183 |
| app/sep/apps/mysql\_backups/spec.py                                                                                   |       25 |        0 |        8 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/views.py                                                                                  |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/xtrabackup\_payload                                                                       |     1512 |     1393 |      570 |       27 |      8% |7-38, 48, 88-143, 145-149, 160, 162-167, 176-351, 380-603, 636, 652-653, 662-1636, 1643-1985, 1991-2140, 2148-2151, 2154-2157, 2161, 2164-2165, 2169-2172, 2175-\>2179, 2180, 2190-2196, 2200-2201, 2205-2207, 2224-2281, 2298, 2334-\>exit, 2342-2353, 2367, 2370, 2373-2374, 2377, 2380, 2387, 2394-2396, 2400-2402, 2405-2406, 2409-2411, 2419, 2432-2454, 2458-2513, 2552-2931 |
| app/sep/apps/nav\_icons.py                                                                                            |       16 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/report/api\_routes.py                                                                                    |       68 |        2 |       18 |        3 |     94% |80, 86-\>90, 195-\>197, 231 |
| app/sep/apps/report/app.py                                                                                            |       27 |        3 |       14 |        6 |     78% |47-\>49, 50, 51-\>53, 54, 56, 57-\>59 |
| app/sep/apps/report/artifact\_store.py                                                                                |       45 |        2 |       10 |        0 |     96% |   149-150 |
| app/sep/apps/report/celery.py                                                                                         |       82 |       19 |       12 |        3 |     74% |87-89, 118-119, 150, 224-226, 229, 232-233, 236-241, 263-267 |
| app/sep/apps/report/deps.py                                                                                           |       16 |        0 |        2 |        1 |     94% | 47-\>exit |
| app/sep/apps/report/job\_service.py                                                                                   |        8 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/report/models.py                                                                                         |      116 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/report/routes.py                                                                                         |       47 |        2 |        0 |        0 |     96% |   195-196 |
| app/sep/apps/report/service.py                                                                                        |      371 |       16 |      128 |       14 |     94% |142, 146, 347, 361-362, 423, 460-461, 463, 467, 468-\>471, 569, 574, 576-\>566, 582, 591, 654, 661 |
| app/sep/apps/shared/backups/columns.py                                                                                |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/shared/backups/edit\_form.py                                                                             |       17 |        0 |       10 |        0 |    100% |           |
| app/sep/apps/shared/backups/responses.py                                                                              |        3 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/shared/disk\_script\_source.py                                                                           |       72 |        2 |       16 |        2 |     95% |  195, 240 |
| app/sep/apps/snippets/app.py                                                                                          |       13 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/snippets/extra\_routes.py                                                                                |       71 |        6 |       10 |        0 |     93% |80-82, 99, 183, 214 |
| app/sep/apps/snippets/routes.py                                                                                       |      100 |       44 |       14 |        0 |     51% |81-83, 112, 122, 135-138, 172-182, 186-188, 199-222, 267-306 |
| app/sep/apps/tasks/api\_routes.py                                                                                     |       27 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/tasks/app.py                                                                                             |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/tasks/deps.py                                                                                            |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/tasks/models.py                                                                                          |       29 |        1 |        2 |        1 |     94% |       115 |
| app/sep/apps/tasks/routes.py                                                                                          |       32 |        0 |        2 |        1 |     97% |   80-\>87 |
| app/sep/apps/tasks/schema.py                                                                                          |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/topology/api\_routes.py                                                                                  |      138 |       13 |       44 |       11 |     87% |92, 121-\>119, 140, 148, 208, 229, 235, 242-\>232, 246, 286, 289-291, 292-\>282, 308-309 |
| app/sep/apps/topology/app.py                                                                                          |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/topology/models.py                                                                                       |      111 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/topology/payloads/topology.py                                                                            |      176 |       81 |       44 |       13 |     52% |67-69, 79, 96-97, 111-113, 115, 119-121, 126, 127-\>123, 129-133, 151-166, 170, 172, 210-211, 246, 261-262, 266-275, 292-293, 295, 324, 357-358, 370-407, 417-422, 426 |
| app/sep/apps/topology/topology.py                                                                                     |      173 |        7 |       58 |        8 |     94% |118-119, 122-\>114, 153, 156-157, 226-\>228, 229-\>231, 407, 491-\>501, 505 |
| app/sep/artifact\_constants.py                                                                                        |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/bundle\_upload/factory.py                                                                                     |       26 |        1 |        4 |        1 |     93% |        64 |
| app/sep/bundle\_upload/plan.py                                                                                        |      163 |        1 |       58 |        1 |     99% |       587 |
| app/sep/bundle\_upload/resolver.py                                                                                    |       28 |        0 |        8 |        0 |    100% |           |
| app/sep/bundle\_upload/seam.py                                                                                        |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/clients/pmm.py                                                                                                |      265 |        2 |       66 |        2 |     99% |  539, 541 |
| app/sep/config.py                                                                                                     |      296 |        9 |       66 |        9 |     95% |177, 226, 415, 546, 560, 564, 566, 568, 823 |
| app/sep/connectivity.py                                                                                               |       79 |        1 |       16 |        1 |     98% |       117 |
| app/sep/crud.py                                                                                                       |       81 |        0 |       10 |        0 |    100% |           |
| app/sep/db/engine.py                                                                                                  |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/db/seed.py                                                                                                    |       39 |        0 |       12 |        0 |    100% |           |
| app/sep/deps.py                                                                                                       |      385 |       10 |       76 |        2 |     97% |449, 452-453, 470, 1123-1124, 1298-1301 |
| app/sep/exceptions.py                                                                                                 |       13 |        0 |        0 |        0 |    100% |           |
| app/sep/inventory.py                                                                                                  |       97 |        8 |       10 |        1 |     92% |81, 92, 229, 286, 326, 363, 385, 419 |
| app/sep/main.py                                                                                                       |      233 |       13 |       38 |        3 |     94% |165-167, 324-341, 501-\>503, 670-\>674, 715-719 |
| app/sep/middleware/csrf.py                                                                                            |       48 |        0 |       14 |        0 |    100% |           |
| app/sep/middleware/messages/\_middleware.py                                                                           |       33 |        0 |        6 |        0 |    100% |           |
| app/sep/middleware/messages/\_utils.py                                                                                |       54 |        1 |       14 |        3 |     94% |119, 264-\>266, 266-\>268 |
| app/sep/middleware/messages/config.py                                                                                 |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/middleware/messages/models.py                                                                                 |       31 |        0 |        4 |        0 |    100% |           |
| app/sep/migrations/\_discovery.py                                                                                     |       41 |        2 |       20 |        3 |     92% |65, 97, 133-\>130 |
| app/sep/migrations/\_orphan\_heads.py                                                                                 |       33 |        0 |        6 |        0 |    100% |           |
| app/sep/migrations/env.py                                                                                             |       41 |        5 |        4 |        2 |     84% |40-\>43, 69-80, 123 |
| app/sep/migrations/versions/2024\_10\_07\_1450-7f4dec8bc76a\_create\_sync\_tables.py                                  |       26 |        8 |        0 |        0 |     69% |     69-76 |
| app/sep/migrations/versions/2024\_10\_08\_2047-eeac2926bbea\_remove\_task\_history\_id\_field.py                      |       12 |        1 |        0 |        0 |     92% |        45 |
| app/sep/migrations/versions/2025\_08\_08\_1005-9307f0f5ee54\_create\_snippet\_table.py                                |       16 |        3 |        0 |        0 |     81% |     59-61 |
| app/sep/migrations/versions/2026\_03\_02\_1612-810c31754b54\_add\_index\_for\_syncinstance\_syncer.py                 |       12 |        1 |        0 |        0 |     92% |        45 |
| app/sep/migrations/versions/2026\_05\_18\_2014-ed97b99eef38\_add\_setting\_override\_table.py                         |       28 |        9 |        4 |        1 |     62% | 44, 87-96 |
| app/sep/migrations/versions/2026\_06\_01\_1530-e5c224619161\_add\_appstate\_table.py                                  |       14 |        2 |        0 |        0 |     86% |     53-54 |
| app/sep/migrations/versions/2026\_06\_02\_1512-378c0872642f\_extend\_setting\_class\_enum\_settings\_alert.py         |       23 |        8 |        4 |        1 |     59% | 47, 77-91 |
| app/sep/migrations/versions/2026\_06\_15\_1725-64f10ead74f6\_add\_seppluginperiodictask.py                            |       16 |        3 |        0 |        0 |     81% |     55-57 |
| app/sep/migrations/versions/2026\_06\_16\_1200-a7c4e9f1b2d3\_add\_lifecycle\_state\_to\_app\_state.py                 |       26 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_16\_1600-b8d5f2a9c1e4\_add\_apprunningtask\_table.py                            |       16 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_22\_1223-410eedfc5b43\_merge\_heads.py                                          |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_22\_1400-c97e7e47c935\_extend\_setting\_class\_enum\_anonymizer.py              |       23 |        8 |        4 |        1 |     59% | 47, 80-93 |
| app/sep/migrations/versions/2026\_06\_30\_1200-a1f4c7e9b2d3\_extend\_setting\_class\_enum\_alerts.py                  |       23 |        8 |        4 |        1 |     59% | 47, 82-95 |
| app/sep/migrations/versions/2026\_07\_02\_1000-f1a2b3c4d5e6\_merge\_heads\_before\_inventory\_settings.py             |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_07\_02\_1001-a2b3c4d5e6f7\_extend\_setting\_class\_enum\_inventory.py               |       25 |        2 |        4 |        2 |     86% |    59, 86 |
| app/sep/models.py                                                                                                     |       66 |        1 |        2 |        1 |     97% |       247 |
| app/sep/periodic\_tasks.py                                                                                            |       55 |        0 |       20 |        0 |    100% |           |
| app/sep/routes/artifacts.py                                                                                           |       38 |        1 |       14 |        1 |     96% |        81 |
| app/sep/routes/download\_files.py                                                                                     |       43 |        0 |        8 |        1 |     98% |   81-\>87 |
| app/sep/routes/execution\_events.py                                                                                   |       14 |        0 |        2 |        0 |    100% |           |
| app/sep/routes/inventory\_ajax.py                                                                                     |       25 |        0 |        0 |        0 |    100% |           |
| app/sep/routes/periodic\_tasks.py                                                                                     |       32 |        1 |        4 |        2 |     92% |80-\>89, 84 |
| app/sep/routes/stop\_task.py                                                                                          |       20 |        0 |        2 |        0 |    100% |           |
| app/sep/routes/stream\_logs.py                                                                                        |       78 |       17 |       12 |        3 |     78% |86, 91-98, 110-115, 117-120, 127-132, 181-\>176, 186-191, 193-197, 202-207 |
| app/sep/settings\_override.py                                                                                         |       31 |        0 |        2 |        0 |    100% |           |
| app/sep/snippets/builtin\_manifest.py                                                                                 |       26 |        0 |        6 |        0 |    100% |           |
| app/sep/snippets/celery.py                                                                                            |       99 |        5 |       40 |        5 |     93% |83, 91-92, 201-\>208, 237, 263 |
| app/sep/snippets/checksums.py                                                                                         |       14 |        0 |        2 |        0 |    100% |           |
| app/sep/snippets/config.py                                                                                            |      131 |       17 |       20 |        7 |     83% |127, 201-207, 220, 270, 352-357, 429-\>448, 436, 447, 463-466 |
| app/sep/snippets/constants.py                                                                                         |        1 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/crud.py                                                                                              |       71 |        0 |       18 |        0 |    100% |           |
| app/sep/snippets/deps.py                                                                                              |      146 |       16 |       44 |        8 |     85% |76, 147-149, 168-\>176, 186, 216, 247, 278, 342-350, 434, 508, 540-547 |
| app/sep/snippets/forms.py                                                                                             |      248 |       10 |       46 |       10 |     92% |181, 518-\>520, 672-675, 863-\>870, 865-\>870, 867, 869, 880, 988, 995, 996-\>1004 |
| app/sep/snippets/list\_query.py                                                                                       |       36 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/masking.py                                                                                           |      158 |        5 |       76 |        5 |     96% |156, 190, 192, 229-230, 321-\>316 |
| app/sep/snippets/models/constants.py                                                                                  |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/models/meta.py                                                                                       |      230 |        1 |       84 |        3 |     99% |535, 714-\>716, 716-\>718 |
| app/sep/snippets/models/responses.py                                                                                  |       28 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/models/snippet.py                                                                                    |      382 |       14 |       90 |        3 |     96% |260-\>283, 284-285, 650-662, 743-745, 873-875 |
| app/sep/snippets/schema.py                                                                                            |       97 |        4 |       34 |        1 |     96% |155-157, 368 |
| app/sep/snippets/script\_source.py                                                                                    |       99 |        4 |       22 |        1 |     94% |294-296, 337 |
| app/sep/snippets/utils.py                                                                                             |       32 |        0 |       10 |        0 |    100% |           |
| app/sep/sync/exceptions.py                                                                                            |       25 |        0 |        0 |        0 |    100% |           |
| app/sep/sync/models.py                                                                                                |      368 |       42 |      100 |       20 |     85% |81-90, 102-\>104, 104-\>106, 125, 131-\>133, 134-\>136, 195-\>201, 273-275, 304-\>302, 336, 396-397, 544, 592, 698-\>exit, 716, 730, 750-751, 786-\>exit, 831, 845, 867-868, 904-\>exit, 949, 962, 986-988, 1021-\>exit, 1130-\>exit, 1169, 1313-1315, 1422-1424, 1429-1435, 1439 |
| app/sep/sync/syncers/mysql/payload.py                                                                                 |      175 |       47 |       54 |        5 |     69% |156-\>164, 240-244, 249-254, 267-273, 277-300, 354-\>370, 373, 394-402, 421 |
| app/sep/sync/syncers/mysql/syncer.py                                                                                  |      222 |        1 |       86 |        7 |     97% |112, 268-\>270, 272-\>274, 586-\>594, 595-\>599, 676-\>687, 762-\>766 |
| app/sep/sync/syncers/pmm.py                                                                                           |       85 |       20 |       28 |        6 |     70% |78-82, 102-105, 116, 171-179, 227, 228-\>224, 231-247, 286-289 |
| app/sep/sync/syncers/system\_facts/payload.py                                                                         |      235 |       19 |       78 |       12 |     90% |52-\>58, 147-148, 176, 222-224, 231, 233-\>229, 244-251, 261-\>263, 263-\>265, 265-\>267, 282-284, 290-292, 316, 415-\>417, 417-\>419, 522, 533 |
| app/sep/sync/syncers/system\_facts/syncer.py                                                                          |      118 |        7 |       28 |        3 |     93% |104, 169-170, 245, 256-\>254, 310-311, 350 |
| app/sep/tasks.py                                                                                                      |       31 |        0 |       12 |        1 |     98% |   69-\>84 |
| app/sep/utils/decorators.py                                                                                           |       10 |        0 |        0 |        0 |    100% |           |
| app/sep/utils/forms.py                                                                                                |       20 |        0 |        6 |        0 |    100% |           |
| app/sep/utils/jinja.py                                                                                                |       61 |       10 |       10 |        1 |     79% |105, 124, 135-140, 171-172 |
| app/sep/utils/static.py                                                                                               |       10 |        0 |        2 |        0 |    100% |           |
| app/tasks/alert\_hooks.py                                                                                             |       23 |        0 |        2 |        0 |    100% |           |
| app/tasks/anonymizer/anonymize.py                                                                                     |       56 |        0 |       18 |        3 |     96% |75-\>82, 97-\>104, 118-\>122 |
| app/tasks/anonymizer/config.py                                                                                        |       30 |        1 |        6 |        1 |     94% |        77 |
| app/tasks/anonymizer/entities.py                                                                                      |       28 |        0 |        2 |        0 |    100% |           |
| app/tasks/celery.py                                                                                                   |      352 |       20 |       78 |        8 |     92% |256-\>268, 265-\>267, 462, 531-533, 703-\>739, 705-722, 754, 873, 942, 965-966, 1067-\>1082 |
| app/tasks/config.py                                                                                                   |       34 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/constants.py                                                                                   |        5 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/models.py                                                                                      |       11 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/payload.py                                                                                     |       69 |        1 |        8 |        1 |     97% |       161 |
| app/tasks/connectivity/routes.py                                                                                      |       16 |        0 |        2 |        0 |    100% |           |
| app/tasks/connectivity/service.py                                                                                     |      145 |        2 |       54 |        6 |     96% |172, 431-\>430, 451-\>450, 457-\>456, 472, 484-\>483 |
| app/tasks/crud.py                                                                                                     |      264 |        3 |       68 |        4 |     98% |438-\>440, 571, 766, 768 |
| app/tasks/db/engine.py                                                                                                |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/db/seed.py                                                                                                  |       68 |       25 |       24 |        3 |     57% |481-\>494, 495-\>509, 511-569, 598 |
| app/tasks/deps.py                                                                                                     |      101 |        3 |       30 |        1 |     97% |61-63, 115-\>124 |
| app/tasks/execution/exceptions.py                                                                                     |        8 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/celery/models.py                                                                        |       82 |        0 |       14 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/exceptions.py                                                                     |        4 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/models.py                                                                         |      710 |       95 |      240 |       21 |     86% |128, 168, 186-189, 190-\>exit, 209, 252, 450, 512-\>514, 630-\>636, 725-\>730, 734, 740, 837-\>833, 894, 896, 952-\>967, 1011-\>1029, 1029-\>1030, 1078, 1081, 1389-1391, 1417-1418, 1455-1456, 1490-1491, 1539-\>1584, 1574-\>1539, 1776-1777, 1781, 1805-1849, 1911-1912, 1986-1987, 2010-2066 |
| app/tasks/execution/models.py                                                                                         |       65 |        0 |       10 |        0 |    100% |           |
| app/tasks/execution/nomad\_lifecycle.py                                                                               |       53 |        0 |       12 |        2 |     97% |125-\>128, 163-\>exit |
| app/tasks/execution/utils.py                                                                                          |       26 |        0 |        6 |        0 |    100% |           |
| app/tasks/hook\_resolver.py                                                                                           |       12 |        0 |        2 |        0 |    100% |           |
| app/tasks/logs/constants.py                                                                                           |        1 |        0 |        0 |        0 |    100% |           |
| app/tasks/logs/line\_split.py                                                                                         |        5 |        0 |        2 |        0 |    100% |           |
| app/tasks/logs/log\_reader.py                                                                                         |      140 |        8 |       62 |        6 |     92% |106, 131, 134, 181-194, 284, 294-\>286 |
| app/tasks/logs/log\_writer.py                                                                                         |      153 |        9 |       66 |        8 |     92% |151-152, 296-297, 444, 448, 450-\>445, 452, 693, 699 |
| app/tasks/main.py                                                                                                     |       72 |        5 |       16 |        1 |     93% |209-210, 216-220 |
| app/tasks/migrations/env.py                                                                                           |       36 |        5 |        4 |        2 |     82% |37-\>44, 64-75, 116 |
| app/tasks/migrations/versions/2024\_09\_18\_1542-04f50684d5d7\_create\_task\_and\_taskhistory\_tables.py              |       34 |       12 |        0 |        0 |     65% |     77-88 |
| app/tasks/migrations/versions/2024\_10\_24\_1528-7920c0e4aa23\_update\_taskbackendenum.py                             |       14 |        2 |        0 |        0 |     86% |     50-51 |
| app/tasks/migrations/versions/2024\_11\_16\_1508-d15d7ea76f80\_use\_enum\_for\_task\_owner.py                         |       16 |        3 |        0 |        0 |     81% |     50-55 |
| app/tasks/migrations/versions/2025\_05\_03\_1359-064c3cec8450\_update\_task\_owner\_enum.py                           |       14 |        2 |        0 |        0 |     86% |     49-50 |
| app/tasks/migrations/versions/2025\_05\_03\_1454-80e592531cd7\_add\_started\_at\_and\_finished\_at\_fields\_.py       |       35 |       18 |       10 |        1 |     40% |61-69, 77-115 |
| app/tasks/migrations/versions/2025\_05\_15\_1933-bec093f02c15\_add\_field\_sync\_in\_progress\_started\_at\_.py       |       14 |        2 |        0 |        0 |     86% |     46-47 |
| app/tasks/migrations/versions/2025\_05\_20\_1144-68379e926e7c\_update\_taskhistory\_status\_enum.py                   |       14 |        2 |        0 |        0 |     86% |     50-51 |
| app/tasks/migrations/versions/2025\_05\_21\_1144-36f2b569e7bb\_create\_dispatchlock\_table.py                         |       14 |        2 |        0 |        0 |     86% |     52-53 |
| app/tasks/migrations/versions/2025\_06\_11\_1021-b4f0b7b50441\_add\_alert\_on\_fail\_field\_to\_task.py               |       12 |        1 |        0 |        0 |     92% |        44 |
| app/tasks/migrations/versions/2025\_08\_05\_2350-19605d228fa3\_add\_anonymize\_mask\_field.py                         |       12 |        1 |        0 |        0 |     92% |        45 |
| app/tasks/migrations/versions/2025\_08\_07\_1757-8f61364b2c2c\_make\_task\_owner\_normal\_string.py                   |       14 |        2 |        0 |        0 |     86% |     46-47 |
| app/tasks/migrations/versions/2025\_08\_22\_2153-d39d37d3dcdc\_migrate\_legacy\_generatedtasks.py                     |      108 |       79 |       34 |        1 |     21% |59-62, 66-67, 71-74, 78-81, 85-113, 117-128, 155-166, 177, 214-221, 225-227, 231-255 |
| app/tasks/migrations/versions/2025\_09\_16\_1745-3b15a15ac473\_add\_anonymize\_mask\_field\_to\_taskhistory.py        |       16 |        3 |        0 |        0 |     81% |     49-51 |
| app/tasks/migrations/versions/2025\_09\_25\_0448-4e346919fc0f\_add\_output\_files\_path\_to\_task.py                  |       12 |        1 |        0 |        0 |     92% |        45 |
| app/tasks/migrations/versions/2025\_10\_07\_1752-0b852d9798ef\_add\_user\_tracking\_fields.py                         |       16 |        3 |        0 |        0 |     81% |     47-49 |
| app/tasks/migrations/versions/2025\_12\_29\_1001-add\_filelock\_requirement\_to\_backup\_tasks.py                     |       87 |       64 |       26 |        1 |     21% |54-73, 78-85, 105-136, 143-187 |
| app/tasks/migrations/versions/2026\_03\_04\_2149-bb3edb973603\_.py                                                    |       13 |        2 |        0 |        0 |     85% |     53-54 |
| app/tasks/migrations/versions/2026\_04\_14\_1000-taskhistory\_log\_create\_taskhistory\_log\_tables.py                |       17 |        4 |        0 |        0 |     76% |   148-156 |
| app/tasks/migrations/versions/2026\_04\_14\_1752-9ebd648709e8\_add\_execution\_request\_json\_indexes.py              |       27 |       12 |       12 |        2 |     44% |64-69, 73-\>exit, 85-94 |
| app/tasks/migrations/versions/2026\_04\_14\_2218-89e80a316a28\_convert\_execution\_request\_to\_jsonb.py              |       18 |        7 |        4 |        1 |     55% |62-67, 74-78 |
| app/tasks/migrations/versions/2026\_04\_21\_1701-e42ce8324da7\_add\_stale\_to\_taskhistory\_status\_enum.py           |       13 |        2 |        0 |        0 |     85% |     55-56 |
| app/tasks/migrations/versions/2026\_05\_18\_2014-fafdb0445092\_add\_setting\_override\_table.py                       |       28 |        9 |        4 |        1 |     62% | 44, 87-96 |
| app/tasks/migrations/versions/2026\_05\_20\_1500-7d1232c0e3ce\_coerce\_alters\_recursion\_method\_host.py             |       37 |       15 |       10 |        1 |     49% |     75-91 |
| app/tasks/migrations/versions/2026\_06\_02\_1512-6d4cfd37bd3a\_extend\_setting\_class\_enum\_settings\_alert.py       |       23 |        8 |        4 |        1 |     59% | 47, 77-91 |
| app/tasks/migrations/versions/2026\_06\_22\_1223-2f5a00236369\_merge\_heads.py                                        |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_06\_22\_1400-abc65df0318a\_extend\_setting\_class\_enum\_anonymizer.py            |       23 |        8 |        4 |        1 |     59% | 47, 80-93 |
| app/tasks/migrations/versions/2026\_06\_22\_1830-c4e8f0a3b1d2\_add\_alert\_detail\_builder\_to\_task.py               |       14 |        1 |        0 |        0 |     93% |        60 |
| app/tasks/migrations/versions/2026\_06\_30\_1200-b2e5d8f0c3a4\_extend\_setting\_class\_enum\_alerts.py                |       23 |        8 |        4 |        1 |     59% | 47, 82-95 |
| app/tasks/migrations/versions/2026\_06\_30\_1200-b7e1c0a4d9f2\_add\_taskhistory\_log\_retention\_index.py             |       25 |        9 |        8 |        2 |     55% |65-66, 70-\>exit, 78-85 |
| app/tasks/migrations/versions/2026\_06\_30\_1838-fa5b80a1c8e0\_merge\_tasks\_migration\_heads.py                      |        9 |        1 |        0 |        0 |     89% |        38 |
| app/tasks/migrations/versions/2026\_06\_30\_1839-e3d856712405\_add\_taskhistory\_log\_stream\_end\_offset\_.py        |       23 |        8 |        4 |        1 |     59% |57-58, 67-74 |
| app/tasks/migrations/versions/2026\_06\_30\_1840-b74f05a17c8d\_rewrite\_persisted\_plugins\_module\_paths\_.py        |       36 |       19 |       16 |        1 |     35% |71-91, 101 |
| app/tasks/migrations/versions/2026\_07\_01\_1142-60bf743eb469\_add\_taskhistory\_log\_state\_nomad\_cursor\_.py       |       14 |        2 |        0 |        0 |     86% |     61-62 |
| app/tasks/migrations/versions/2026\_07\_01\_1142-f028a195fbda\_merge\_tasks\_migration\_heads.py                      |        9 |        1 |        0 |        0 |     89% |        38 |
| app/tasks/migrations/versions/2026\_07\_01\_1848-8657d05d27da\_merge\_tasks\_migration\_heads.py                      |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_07\_02\_1001-b3c4d5e6f7a8\_extend\_setting\_class\_enum\_inventory.py             |       25 |        8 |        4 |        1 |     62% | 59, 81-91 |
| app/tasks/migrations/versions/2026\_07\_03\_1200-a1f4c9e2b7d8\_add\_taskhistory\_log\_allocation\_epoch.py            |       11 |        1 |        0 |        0 |     91% |        57 |
| app/tasks/migrations/versions/2026\_07\_06\_1303-d25887ee3fea\_merge\_tasks\_migration\_heads.py                      |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_07\_06\_1900-13e897d11734\_relativize\_task\_payload\_refs.py                     |       48 |        2 |       16 |        2 |     94% |   74, 105 |
| app/tasks/migrations/versions/2026\_07\_25\_0217-27a11549ef43\_add\_run\_result\_recorder\_to\_task.py                |       12 |        0 |        0 |        0 |    100% |           |
| app/tasks/models.py                                                                                                   |      334 |        4 |       66 |        5 |     98% |213, 597-\>600, 604, 619-\>625, 1134-\>1136, 1146-\>1148, 1171-1172 |
| app/tasks/periodic/crud.py                                                                                            |       26 |        0 |        0 |        0 |    100% |           |
| app/tasks/periodic/deps.py                                                                                            |       11 |        0 |        0 |        0 |    100% |           |
| app/tasks/periodic/models.py                                                                                          |      111 |        5 |       34 |        5 |     93% |220, 255, 309, 325, 394 |
| app/tasks/periodic/routes.py                                                                                          |       60 |        5 |       12 |        3 |     89% |65-71, 121-\>123, 143-146, 159 |
| app/tasks/periodic/utils.py                                                                                           |       22 |        0 |        6 |        1 |     96% |   85-\>86 |
| app/tasks/routes.py                                                                                                   |      232 |       22 |       46 |        4 |     89% |142-146, 229-235, 268, 318-324, 331, 375-376, 404, 444, 463, 627, 641, 649, 675, 683-\>685, 706-707 |
| app/tasks/run\_result.py                                                                                              |       59 |        0 |       14 |        0 |    100% |           |
| app/tasks/settings/routes.py                                                                                          |       11 |        0 |        0 |        0 |    100% |           |
| **TOTAL**                                                                                                             | **34550** | **7174** | **9042** |  **763** | **77%** |           |


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