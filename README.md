# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/percona/SEP/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                                                                         |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------------------------------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| app/api/deps.py                                                                                                              |       78 |        0 |       20 |        0 |    100% |           |
| app/api/main.py                                                                                                              |        6 |        0 |        0 |        0 |    100% |           |
| app/api/routes/config.py                                                                                                     |        9 |        0 |        0 |        0 |    100% |           |
| app/api/routes/oauth.py                                                                                                      |       77 |        0 |       14 |        0 |    100% |           |
| app/api/routes/users.py                                                                                                      |       21 |        0 |        4 |        0 |    100% |           |
| app/celery.py                                                                                                                |       34 |        4 |        2 |        0 |     89% | 51, 57-59 |
| app/core/alerts/config.py                                                                                                    |       43 |        0 |        4 |        0 |    100% |           |
| app/core/alerts/models.py                                                                                                    |       57 |        0 |       10 |        0 |    100% |           |
| app/core/alerts/providers/pagerduty.py                                                                                       |       35 |        1 |        0 |        0 |     97% |       110 |
| app/core/auth/base.py                                                                                                        |       14 |        2 |        0 |        0 |     86% |    63, 81 |
| app/core/auth/config.py                                                                                                      |       79 |        2 |       22 |        2 |     96% |  118, 161 |
| app/core/auth/exceptions.py                                                                                                  |       11 |        0 |        0 |        0 |    100% |           |
| app/core/auth/models.py                                                                                                      |       94 |        0 |        2 |        0 |    100% |           |
| app/core/auth/providers/casdoor/models.py                                                                                    |       93 |        5 |       16 |        0 |     92% |   229-235 |
| app/core/auth/providers/casdoor/provider.py                                                                                  |       14 |        0 |        0 |        0 |    100% |           |
| app/core/auth/providers/casdoor/sdk.py                                                                                       |      123 |       51 |       26 |        3 |     54% |51, 106-107, 118, 145-\>147, 161-170, 189-190, 209-216, 240-260, 268, 287-295, 309-310, 342-\>341, 360-365, 373-374, 387, 397-401, 411-415 |
| app/core/auth/providers/grafana/models.py                                                                                    |      184 |        3 |       38 |        1 |     98% |375, 672-673 |
| app/core/auth/providers/grafana/provider.py                                                                                  |       25 |        0 |        4 |        0 |    100% |           |
| app/core/auth/providers/grafana/sdk.py                                                                                       |       54 |        0 |        6 |        0 |    100% |           |
| app/core/auth/utils.py                                                                                                       |        6 |        1 |        0 |        0 |     83% |        35 |
| app/core/celery/config.py                                                                                                    |       33 |        0 |        2 |        0 |    100% |           |
| app/core/celery/crud.py                                                                                                      |       26 |        2 |        4 |        1 |     90% |     91-97 |
| app/core/celery/db.py                                                                                                        |        8 |        0 |        0 |        0 |    100% |           |
| app/core/celery/deps.py                                                                                                      |       10 |        0 |        0 |        0 |    100% |           |
| app/core/celery/models.py                                                                                                    |       36 |        2 |        6 |        2 |     90% |   72, 135 |
| app/core/celery/utils.py                                                                                                     |       31 |        2 |       10 |        2 |     90% |   92, 120 |
| app/core/config.py                                                                                                           |      252 |        5 |       48 |        4 |     97% |235-\>exit, 531, 750, 826, 839, 877-\>879, 882 |
| app/core/db/config.py                                                                                                        |       35 |        0 |        6 |        0 |    100% |           |
| app/core/db/crud.py                                                                                                          |      301 |       21 |       84 |        9 |     91% |197, 250-\>252, 252-\>254, 254-\>256, 263-\>279, 314-331, 349, 354, 371, 485-488, 902, 906, 1197-1198 |
| app/core/db/list\_query.py                                                                                                   |       87 |        0 |       24 |        0 |    100% |           |
| app/core/db/models.py                                                                                                        |       14 |        0 |        0 |        0 |    100% |           |
| app/core/db/sql\_types.py                                                                                                    |       37 |        0 |       12 |        0 |    100% |           |
| app/core/db/utils.py                                                                                                         |       90 |        5 |       26 |        5 |     91% |107, 294, 323, 326, 344 |
| app/core/exceptions.py                                                                                                       |       26 |        0 |        0 |        0 |    100% |           |
| app/core/health.py                                                                                                           |       79 |        0 |       12 |        0 |    100% |           |
| app/core/log.py                                                                                                              |       41 |        0 |       16 |        0 |    100% |           |
| app/core/middleware/log\_context.py                                                                                          |       26 |        0 |        2 |        0 |    100% |           |
| app/core/middleware/security\_headers.py                                                                                     |      105 |        0 |       20 |        1 |     99% |221-\>exit |
| app/core/models.py                                                                                                           |       20 |        0 |        2 |        0 |    100% |           |
| app/core/pagination/deps.py                                                                                                  |       17 |        0 |        2 |        0 |    100% |           |
| app/core/pagination/models.py                                                                                                |       78 |        1 |       20 |        1 |     98% |        77 |
| app/core/pmm.py                                                                                                              |       51 |        1 |       10 |        1 |     97% |        53 |
| app/core/requests/connectivity.py                                                                                            |       29 |        0 |        8 |        0 |    100% |           |
| app/core/requests/registry.py                                                                                                |       64 |        5 |       22 |        5 |     88% |101, 112, 158, 169, 179 |
| app/core/requests/remote\_api.py                                                                                             |      301 |        2 |       64 |        3 |     99% |247, 266, 735-\>734 |
| app/core/security.py                                                                                                         |       18 |        0 |        4 |        0 |    100% |           |
| app/core/settings\_override/api/export.py                                                                                    |       10 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/api/models.py                                                                                    |       22 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/api/routes.py                                                                                    |      300 |       35 |      100 |        8 |     86% |322, 456, 480, 610-617, 745, 773-783, 816-824, 832, 957, 987, 1047-1048, 1126, 1128, 1130, 1153, 1359-\>1390, 1367-1376, 1380-1389 |
| app/core/settings\_override/cache.py                                                                                         |      118 |       13 |       46 |        6 |     86% |197-202, 215-220, 302, 365, 406, 410-417 |
| app/core/settings\_override/constants.py                                                                                     |        1 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/lifecycle.py                                                                                     |       95 |        2 |       24 |        1 |     97% |   64, 357 |
| app/core/settings\_override/manager.py                                                                                       |        5 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/models.py                                                                                        |       24 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/policy.py                                                                                        |       30 |        0 |        6 |        0 |    100% |           |
| app/core/settings\_override/proxy.py                                                                                         |       22 |        0 |        2 |        0 |    100% |           |
| app/core/settings\_override/registry.py                                                                                      |      653 |       48 |      332 |       30 |     91% |790, 849, 992, 1045, 1079, 1094, 1152, 1370, 1430, 1495-1496, 1500, 1501-\>1487, 1502-\>1501, 1532, 1537, 1574, 1603, 1622, 1721, 1726, 1752, 1780-\>1775, 1803-1809, 1840, 1843, 1870-1871, 1885-1895, 1922-1925, 1934, 1941-1944, 2070 |
| app/core/settings\_override/worker.py                                                                                        |       28 |        0 |        6 |        0 |    100% |           |
| app/core/utils/async\_run.py                                                                                                 |       13 |        0 |        0 |        0 |    100% |           |
| app/core/utils/cache.py                                                                                                      |       92 |        5 |       18 |        4 |     90% |60-62, 147-\>153, 151, 186-\>191, 223 |
| app/core/utils/cli\_args.py                                                                                                  |       12 |        0 |        0 |        0 |    100% |           |
| app/core/utils/date\_time.py                                                                                                 |        8 |        0 |        2 |        0 |    100% |           |
| app/core/utils/dict.py                                                                                                       |       29 |        4 |       12 |        0 |     85% |   165-168 |
| app/core/utils/fields.py                                                                                                     |      233 |        7 |       30 |        5 |     95% |171, 243-244, 411, 415, 636, 684 |
| app/core/utils/imports.py                                                                                                    |       28 |        0 |        8 |        0 |    100% |           |
| app/core/utils/iterators.py                                                                                                  |       18 |        0 |        6 |        0 |    100% |           |
| app/core/utils/json\_pointer.py                                                                                              |       41 |        0 |       22 |        0 |    100% |           |
| app/core/utils/lazy.py                                                                                                       |       31 |        0 |        4 |        0 |    100% |           |
| app/core/utils/openapi.py                                                                                                    |      246 |        5 |      120 |        7 |     96% |141, 513, 515-\>514, 520-521, 564-\>566, 583-\>582, 600 |
| app/core/utils/path.py                                                                                                       |       40 |        0 |       14 |        0 |    100% |           |
| app/core/utils/pydantic.py                                                                                                   |       63 |        0 |       22 |        0 |    100% |           |
| app/core/utils/serialization.py                                                                                              |        7 |        0 |        0 |        0 |    100% |           |
| app/core/utils/strings.py                                                                                                    |       24 |        3 |        4 |        1 |     79% |     64-69 |
| app/inventory/config.py                                                                                                      |       12 |        0 |        0 |        0 |    100% |           |
| app/inventory/constants.py                                                                                                   |        4 |        0 |        0 |        0 |    100% |           |
| app/inventory/crud.py                                                                                                        |       30 |        0 |        0 |        0 |    100% |           |
| app/inventory/db.py                                                                                                          |        6 |        0 |        0 |        0 |    100% |           |
| app/inventory/deps.py                                                                                                        |       43 |        9 |        4 |        0 |     72% |58-60, 156-158, 177-179 |
| app/inventory/main.py                                                                                                        |       44 |        8 |        2 |        1 |     80% |52, 97-98, 130-131, 135-139 |
| app/inventory/models.py                                                                                                      |       92 |        0 |        4 |        0 |    100% |           |
| app/inventory/routes/nodes.py                                                                                                |       52 |        2 |        4 |        0 |     93% |  140, 142 |
| app/inventory/routes/schemas.py                                                                                              |       34 |        0 |        0 |        0 |    100% |           |
| app/inventory/routes/services.py                                                                                             |       48 |        3 |        4 |        0 |     87% |129, 131, 165 |
| app/inventory/routes/tables.py                                                                                               |       26 |        0 |        0 |        0 |    100% |           |
| app/inventory/settings/routes.py                                                                                             |       12 |        0 |        0 |        0 |    100% |           |
| app/main.py                                                                                                                  |       91 |       23 |        6 |        1 |     73% |   252-306 |
| app/sep/api/constants.py                                                                                                     |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/api/host\_resolution.py                                                                                              |        9 |        0 |        4 |        0 |    100% |           |
| app/sep/api/models.py                                                                                                        |       13 |        0 |        0 |        0 |    100% |           |
| app/sep/api/openapi.py                                                                                                       |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/api/proxy.py                                                                                                         |       16 |        0 |        2 |        0 |    100% |           |
| app/sep/api/router.py                                                                                                        |       39 |        0 |        4 |        0 |    100% |           |
| app/sep/api/routes/app\_info.py                                                                                              |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/app\_state.py                                                                                             |       44 |       12 |       10 |        2 |     59% |180, 186, 188-195, 202, 208-209, 237-238, 243-244, 251 |
| app/sep/api/routes/apps.py                                                                                                   |       22 |        3 |        2 |        1 |     83% |87, 107-108 |
| app/sep/api/routes/connectivity\_check.py                                                                                    |       55 |        0 |       18 |        0 |    100% |           |
| app/sep/api/routes/dashboard.py                                                                                              |       35 |        0 |        6 |        0 |    100% |           |
| app/sep/api/routes/hosts.py                                                                                                  |       22 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/periodic\_tasks.py                                                                                        |       29 |        0 |        2 |        0 |    100% |           |
| app/sep/api/routes/schemas.py                                                                                                |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/services.py                                                                                               |       17 |        0 |        2 |        0 |    100% |           |
| app/sep/api/routes/settings.py                                                                                               |      129 |        6 |       50 |        3 |     94% |131, 136, 291-293, 321 |
| app/sep/api/routes/task\_history.py                                                                                          |       27 |        0 |        4 |        0 |    100% |           |
| app/sep/api/routes/task\_stats.py                                                                                            |       13 |        0 |        0 |        0 |    100% |           |
| app/sep/api/task\_history\_merge.py                                                                                          |       55 |        4 |       16 |        3 |     90% |57, 61-62, 113, 115-\>117 |
| app/sep/app\_drain.py                                                                                                        |       83 |        2 |       14 |        2 |     96% |137-\>139, 206, 212 |
| app/sep/apps/alert\_troubleshooting/api\_routes.py                                                                           |       23 |        4 |        2 |        0 |     76% |64-65, 73-80 |
| app/sep/apps/alert\_troubleshooting/app.py                                                                                   |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alert\_troubleshooting/deps.py                                                                                  |      108 |        4 |       44 |        3 |     95% |107, 109-\>111, 222, 235, 319 |
| app/sep/apps/alert\_troubleshooting/models.py                                                                                |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alert\_troubleshooting/schema.py                                                                                |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/api\_routes.py                                                                                           |      124 |       16 |       16 |        0 |     86% |178, 194-197, 242-252 |
| app/sep/apps/alerts/app.py                                                                                                   |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/app\_owned\_settings.py                                                                                  |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/celery.py                                                                                                |       46 |        1 |       10 |        0 |     98% |        39 |
| app/sep/apps/alerts/config.py                                                                                                |       14 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/crud.py                                                                                                  |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/deps.py                                                                                                  |       75 |        0 |       16 |        0 |    100% |           |
| app/sep/apps/alerts/loader.py                                                                                                |       22 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/alerts/migrations/versions/2026\_04\_20\_1817-d21ad387df7a\_create\_alert\_backup\_table.py                     |       14 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/alerts/models.py                                                                                                |       46 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/restore.py                                                                                               |       95 |        0 |       26 |        0 |    100% |           |
| app/sep/apps/alters/api\_routes.py                                                                                           |       38 |        3 |        0 |        0 |     92% |82, 140-145 |
| app/sep/apps/alters/app.py                                                                                                   |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alters/deps.py                                                                                                  |      209 |       12 |       62 |       11 |     92% |98, 128-\>140, 134-\>133, 138-\>133, 141, 344, 411-412, 470, 553, 576-577, 697, 708, 710, 749-\>753 |
| app/sep/apps/alters/form\_backfill.py                                                                                        |       32 |        1 |       10 |        1 |     95% |       100 |
| app/sep/apps/alters/models.py                                                                                                |       49 |        1 |        6 |        1 |     96% |       121 |
| app/sep/apps/alters/schema.py                                                                                                |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alters/spec.py                                                                                                  |       42 |        1 |       18 |        1 |     97% |        52 |
| app/sep/apps/alters/views.py                                                                                                 |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/archives/alerts.py                                                                                              |      130 |        6 |       40 |        4 |     94% |178, 213, 255, 338-339, 349, 371-\>376 |
| app/sep/apps/archives/app.py                                                                                                 |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/archives/constants.py                                                                                           |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/archives/form\_backfill.py                                                                                      |      141 |       16 |       72 |       16 |     85% |41, 54, 57, 66-67, 69, 73, 80, 100, 116, 165-\>167, 179-\>182, 184, 194, 224, 228, 236, 278 |
| app/sep/apps/archives/models.py                                                                                              |       76 |        0 |        4 |        0 |    100% |           |
| app/sep/apps/archives/spec.py                                                                                                |       55 |       10 |       24 |        7 |     76% |106, 133, 156-\>164, 166, 173, 177-180, 182-183 |
| app/sep/apps/archives/views.py                                                                                               |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/api\_routes.py                                                                                              |      213 |       47 |       38 |        3 |     75% |193-\>203, 252, 270, 285, 384-385, 389-395, 458-471, 473-489, 498, 500-516, 536-538, 665-\>672, 666, 722-728, 730-733, 751, 769, 808 |
| app/sep/apps/atw/app.py                                                                                                      |       12 |        1 |        2 |        1 |     86% |        47 |
| app/sep/apps/atw/batch.py                                                                                                    |       74 |        0 |        8 |        0 |    100% |           |
| app/sep/apps/atw/categories.py                                                                                               |       34 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/atw/celery.py                                                                                                   |       18 |        5 |        2 |        0 |     65% | 42, 54-57 |
| app/sep/apps/atw/config.py                                                                                                   |       15 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/crud.py                                                                                                     |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/deps.py                                                                                                     |       34 |        0 |        8 |        0 |    100% |           |
| app/sep/apps/atw/migrations/versions/2026\_07\_20\_1238-b82887dfe93d\_create\_atw\_incident\_tables.py                       |       24 |        7 |        8 |        2 |     59% |40-\>55, 55-\>exit, 85-94 |
| app/sep/apps/atw/migrations/versions/2026\_07\_24\_1100-c93998e0fa14\_create\_atw\_send\_log\_table.py                       |       20 |        5 |        4 |        1 |     67% |40-\>exit, 81-87 |
| app/sep/apps/atw/migrations/versions/2026\_07\_30\_1200-447ee0172734\_add\_atw\_incident\_closed\_at.py                      |       25 |        2 |        8 |        4 |     82% |41, 43-\>exit, 55, 57-\>exit |
| app/sep/apps/atw/models.py                                                                                                   |       59 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/schema.py                                                                                                   |       13 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/atw/send.py                                                                                                     |      264 |        7 |       48 |        0 |     98% |107, 163, 175, 305, 474, 810-811 |
| app/sep/apps/backup\_mongo/api\_routes.py                                                                                    |       30 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/app.py                                                                                            |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/deps.py                                                                                           |      115 |       14 |       18 |        0 |     83% |   240-259 |
| app/sep/apps/backup\_mongo/models.py                                                                                         |      239 |        0 |       42 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/pbm\_creds\_common.py                                                                             |      159 |        3 |       32 |        1 |     98% |83-\>92, 147-149 |
| app/sep/apps/backup\_mongo/restore/api\_routes.py                                                                            |       34 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/app.py                                                                                    |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/deps.py                                                                                   |      138 |        7 |       18 |        2 |     94% |179, 423-439, 454 |
| app/sep/apps/backup\_mongo/restore/models.py                                                                                 |      159 |        7 |       22 |        5 |     93% |79-81, 83, 86-90, 302-\>306, 340-\>342, 640 |
| app/sep/apps/backup\_mongo/restore/schema.py                                                                                 |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/spec.py                                                                                   |       31 |        2 |        0 |        0 |     94% |   190-191 |
| app/sep/apps/backup\_mongo/restore/views.py                                                                                  |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/schema.py                                                                                         |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/spec.py                                                                                           |       49 |        2 |       22 |        3 |     93% |85-\>88, 129, 134 |
| app/sep/apps/backup\_mongo/views.py                                                                                          |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/app.py                                                                                               |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/deps.py                                                                                              |       57 |        6 |       10 |        1 |     90% |57-58, 61, 95-97 |
| app/sep/apps/backup\_pg/form\_backfill.py                                                                                    |       46 |        4 |       16 |        4 |     87% |44-\>57, 47-48, 49-\>57, 51-\>57, 53-\>57, 85-86 |
| app/sep/apps/backup\_pg/models.py                                                                                            |       48 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/spec.py                                                                                              |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/views.py                                                                                             |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/checksums/app.py                                                                                                |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/checksums/deps.py                                                                                               |       18 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/checksums/form\_backfill.py                                                                                     |       48 |        4 |       24 |        5 |     88% |55, 63, 70, 91, 109-\>108 |
| app/sep/apps/checksums/models.py                                                                                             |       75 |        4 |       20 |        4 |     92% |53, 55, 58, 313 |
| app/sep/apps/checksums/spec.py                                                                                               |       68 |        0 |       26 |        2 |     98% |115-\>123, 190-\>192 |
| app/sep/apps/checksums/views.py                                                                                              |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/api\_routes.py                                                                                           |       67 |        4 |        4 |        1 |     93% |83-84, 140-141 |
| app/sep/apps/dipper/app.py                                                                                                   |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/constants.py                                                                                             |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/deps.py                                                                                                  |      120 |       14 |       34 |        8 |     83% |120-122, 143-144, 184-187, 188-\>195, 218, 219-\>221, 278, 280, 282, 391 |
| app/sep/apps/dipper/models.py                                                                                                |       17 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/schema.py                                                                                                |       36 |        1 |       10 |        1 |     96% |       238 |
| app/sep/apps/field\_names.py                                                                                                 |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/framework/api.py                                                                                                |      331 |       10 |      130 |        8 |     96% |141-\>139, 196-201, 723, 730, 858, 864, 869, 875, 890, 1297 |
| app/sep/apps/framework/apps.py                                                                                               |      342 |        7 |      138 |        7 |     97% |539, 703, 719, 736, 796, 810, 817 |
| app/sep/apps/framework/base.py                                                                                               |       44 |        2 |        6 |        2 |     92% |  153, 160 |
| app/sep/apps/framework/cascade.py                                                                                            |      189 |        0 |       62 |        2 |     99% |131-\>133, 147-\>149 |
| app/sep/apps/framework/conformance.py                                                                                        |      100 |        9 |       52 |        7 |     88% |69, 174, 200-204, 268, 281, 285, 333 |
| app/sep/apps/framework/connectivity.py                                                                                       |       25 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/framework/deps.py                                                                                               |       15 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/framework/form\_backfill.py                                                                                     |      170 |       34 |       30 |        4 |     79% |109, 114, 119, 124, 129, 251-257, 260-265, 283-289, 292, 376-\>383, 406-445, 534 |
| app/sep/apps/framework/form\_backfill\_guards.py                                                                             |       10 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/framework/form\_backfill\_inventory.py                                                                          |      141 |       12 |       52 |       12 |     88% |71, 76-\>exit, 144, 147, 151, 164-\>142, 196, 199-\>212, 216, 249, 267, 280-281, 290-295, 317-\>323 |
| app/sep/apps/framework/form\_backfill\_registry.py                                                                           |       44 |        0 |       14 |        0 |    100% |           |
| app/sep/apps/framework/form\_dsl/conformance.py                                                                              |       46 |        9 |       18 |        3 |     75% |65, 69, 85-93 |
| app/sep/apps/framework/form\_dsl/derivation.py                                                                               |      350 |       22 |      178 |       23 |     91% |258, 275, 451, 467, 474, 480-\>476, 489, 499-\>505, 502-504, 518-\>520, 523, 525-\>520, 527, 544, 550, 565, 568, 576, 582-583, 585, 636, 642, 836 |
| app/sep/apps/framework/form\_dsl/markers.py                                                                                  |      121 |        1 |       14 |        1 |     99% |       189 |
| app/sep/apps/framework/form\_dsl/model.py                                                                                    |       17 |        1 |        2 |        1 |     89% |        70 |
| app/sep/apps/framework/form\_dsl/pt\_toolkit.py                                                                              |       56 |        0 |       26 |        0 |    100% |           |
| app/sep/apps/framework/list\_query.py                                                                                        |       73 |        0 |       14 |        0 |    100% |           |
| app/sep/apps/framework/registry.py                                                                                           |      177 |        4 |       92 |        4 |     97% |409, 415, 417, 436 |
| app/sep/apps/framework/responses.py                                                                                          |       95 |        1 |       20 |        1 |     98% |        63 |
| app/sep/apps/framework/rules.py                                                                                              |      538 |        7 |      130 |        5 |     98% |323, 328, 333, 545, 861, 1348, 1368 |
| app/sep/apps/framework/scaffold.py                                                                                           |      429 |       29 |      150 |       20 |     91% |281, 292, 304, 421, 516, 519, 539-\>546, 542, 593-595, 629, 670, 674, 874, 1103-1106, 1132, 1134, 1148-1151, 1177, 1182-1185, 1204, 1244 |
| app/sep/apps/framework/schema.py                                                                                             |      392 |        2 |      114 |        2 |     99% |1327, 1779 |
| app/sep/apps/framework/script\_helpers.py                                                                                    |       44 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/framework/script\_source.py                                                                                     |       63 |        0 |       14 |        0 |    100% |           |
| app/sep/apps/framework/spec.py                                                                                               |      151 |        0 |       68 |        0 |    100% |           |
| app/sep/apps/framework/task\_status.py                                                                                       |       44 |        0 |       14 |        0 |    100% |           |
| app/sep/apps/inventory/api\_routes.py                                                                                        |       78 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/app.py                                                                                                |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/connectivity.py                                                                                       |       42 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/inventory/constants.py                                                                                          |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/deps.py                                                                                               |      138 |       13 |       54 |        3 |     90% |276-300, 412-417, 460, 467 |
| app/sep/apps/inventory/list\_query.py                                                                                        |       29 |        1 |        4 |        1 |     94% |       118 |
| app/sep/apps/inventory/models.py                                                                                             |       29 |        7 |        8 |        3 |     68% |92, 94, 95-\>97, 113-121 |
| app/sep/apps/inventory/schema.py                                                                                             |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/sync.py                                                                                               |       30 |        0 |       12 |        0 |    100% |           |
| app/sep/apps/labels.py                                                                                                       |        1 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/meta\_keys.py                                                                                                   |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/api\_routes.py                                                                                   |       18 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/app.py                                                                                           |       14 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/backup\_source\_choices.py                                                                       |       62 |       11 |       24 |        1 |     77% |   148-158 |
| app/sep/apps/mysql\_backups/crud.py                                                                                          |       19 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/deps.py                                                                                          |       66 |        1 |       12 |        2 |     96% |65, 212-\>215 |
| app/sep/apps/mysql\_backups/form\_backfill.py                                                                                |       56 |        6 |       20 |        7 |     83% |73-\>95, 76-77, 78-\>95, 80-\>95, 82-\>95, 86-\>95, 89, 119-120, 130 |
| app/sep/apps/mysql\_backups/forms.py                                                                                         |      186 |        2 |       14 |        2 |     98% |  647, 662 |
| app/sep/apps/mysql\_backups/migrations/versions/2026\_07\_29\_1200-f0a1b2c3d4e5\_create\_mysql\_backup\_run\_table.py        |       22 |        6 |        4 |        1 |     65% |40-\>exit, 89-98 |
| app/sep/apps/mysql\_backups/migrations/versions/2026\_08\_06\_1200-b7c8d9e0f1a2\_add\_service\_id\_to\_mysql\_backup\_run.py |       30 |        0 |       12 |        2 |     95% |66-\>exit, 74-\>exit |
| app/sep/apps/mysql\_backups/models.py                                                                                        |       49 |        0 |        4 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/payload\_variants.py                                                                             |       13 |        0 |        4 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/recorder.py                                                                                      |       43 |        0 |       10 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/restore/app.py                                                                                   |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/restore/deps.py                                                                                  |       80 |       14 |       20 |        5 |     79% |70, 83-\>87, 104-115, 154-155, 159, 164, 167-168 |
| app/sep/apps/mysql\_backups/restore/form\_backfill.py                                                                        |       55 |        3 |       18 |        1 |     95% |127-128, 141 |
| app/sep/apps/mysql\_backups/restore/models.py                                                                                |      141 |        2 |       14 |        2 |     97% |   52, 477 |
| app/sep/apps/mysql\_backups/restore/spec.py                                                                                  |       35 |        1 |        8 |        1 |     95% |       106 |
| app/sep/apps/mysql\_backups/restore/views.py                                                                                 |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/spec.py                                                                                          |       32 |        1 |       10 |        1 |     95% |       135 |
| app/sep/apps/mysql\_backups/views.py                                                                                         |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/nav\_icons.py                                                                                                   |       16 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/report/api\_routes.py                                                                                           |       68 |        2 |       18 |        3 |     94% |80, 86-\>90, 195-\>197, 231 |
| app/sep/apps/report/app.py                                                                                                   |       26 |        3 |       14 |        6 |     78% |47-\>49, 50, 51-\>53, 54, 56, 57-\>59 |
| app/sep/apps/report/app\_owned\_settings.py                                                                                  |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/report/artifact\_store.py                                                                                       |       45 |        2 |       10 |        0 |     96% |   149-150 |
| app/sep/apps/report/celery.py                                                                                                |       82 |       19 |       12 |        3 |     74% |87-89, 118-119, 150, 224-226, 229, 232-233, 236-241, 263-267 |
| app/sep/apps/report/config.py                                                                                                |       71 |        5 |       18 |        5 |     89% |138, 152, 156, 158, 160 |
| app/sep/apps/report/deps.py                                                                                                  |        1 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/report/job\_service.py                                                                                          |        8 |        1 |        2 |        0 |     90% |        43 |
| app/sep/apps/report/models.py                                                                                                |      117 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/report/service.py                                                                                               |      379 |       16 |      128 |       14 |     94% |144, 148, 349, 363-364, 425, 462-463, 465, 469, 470-\>473, 571, 576, 578-\>568, 584, 593, 656, 663 |
| app/sep/apps/shared/backups/columns.py                                                                                       |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/shared/backups/edit\_form.py                                                                                    |       17 |        0 |       10 |        0 |    100% |           |
| app/sep/apps/shared/backups/responses.py                                                                                     |        3 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/shared/disk\_script\_source.py                                                                                  |       81 |        2 |       18 |        2 |     96% |  213, 258 |
| app/sep/apps/snippets/app.py                                                                                                 |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/snippets/extra\_routes.py                                                                                       |       71 |        6 |       10 |        0 |     93% |80-82, 99, 183, 214 |
| app/sep/apps/tasks/api\_routes.py                                                                                            |       27 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/tasks/app.py                                                                                                    |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/tasks/deps.py                                                                                                   |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/tasks/models.py                                                                                                 |       29 |        1 |        2 |        1 |     94% |       115 |
| app/sep/apps/tasks/schema.py                                                                                                 |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/topology/api\_routes.py                                                                                         |      138 |       13 |       44 |       11 |     87% |91, 120-\>118, 139, 147, 202, 223, 229, 236-\>226, 240, 280, 283-285, 286-\>276, 302-303 |
| app/sep/apps/topology/app.py                                                                                                 |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/topology/models.py                                                                                              |      112 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/topology/topology.py                                                                                            |      173 |        7 |       58 |        8 |     94% |118-119, 122-\>114, 153, 156-157, 226-\>228, 229-\>231, 407, 491-\>501, 505 |
| app/sep/artifact\_constants.py                                                                                               |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/bundle\_upload/factory.py                                                                                            |       28 |        1 |        4 |        1 |     94% |        67 |
| app/sep/bundle\_upload/plan.py                                                                                               |      163 |        1 |       58 |        1 |     99% |       587 |
| app/sep/bundle\_upload/resolver.py                                                                                           |       46 |        0 |       12 |        0 |    100% |           |
| app/sep/bundle\_upload/seam.py                                                                                               |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/clients/pmm.py                                                                                                       |      265 |        2 |       66 |        2 |     99% |  539, 541 |
| app/sep/config.py                                                                                                            |      230 |        4 |       54 |        4 |     97% |180, 229, 405, 695 |
| app/sep/connectivity.py                                                                                                      |       39 |        4 |        2 |        1 |     88% |84, 163-169 |
| app/sep/crud.py                                                                                                              |       81 |        0 |       10 |        0 |    100% |           |
| app/sep/db/engine.py                                                                                                         |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/db/seed.py                                                                                                           |       39 |        0 |       12 |        0 |    100% |           |
| app/sep/deps.py                                                                                                              |      252 |        2 |       48 |        1 |     99% |239, 628-\>633, 649 |
| app/sep/inventory.py                                                                                                         |       99 |        6 |       12 |        2 |     93% |86, 97, 233, 289, 309-\>311, 329, 366 |
| app/sep/main.py                                                                                                              |      120 |       15 |       12 |        2 |     87% |160-162, 287-306, 326-\>335, 460-464 |
| app/sep/migrations/\_discovery.py                                                                                            |       41 |        2 |       20 |        3 |     92% |65, 97, 133-\>130 |
| app/sep/migrations/\_orphan\_heads.py                                                                                        |       33 |        0 |        6 |        0 |    100% |           |
| app/sep/migrations/env.py                                                                                                    |       41 |        5 |        4 |        2 |     84% |40-\>43, 69-80, 123 |
| app/sep/migrations/versions/2024\_10\_07\_1450-7f4dec8bc76a\_create\_sync\_tables.py                                         |       26 |        8 |        0 |        0 |     69% |     69-76 |
| app/sep/migrations/versions/2024\_10\_08\_2047-eeac2926bbea\_remove\_task\_history\_id\_field.py                             |       12 |        1 |        0 |        0 |     92% |        45 |
| app/sep/migrations/versions/2025\_08\_08\_1005-9307f0f5ee54\_create\_snippet\_table.py                                       |       16 |        3 |        0 |        0 |     81% |     59-61 |
| app/sep/migrations/versions/2026\_03\_02\_1612-810c31754b54\_add\_index\_for\_syncinstance\_syncer.py                        |       12 |        1 |        0 |        0 |     92% |        45 |
| app/sep/migrations/versions/2026\_05\_18\_2014-ed97b99eef38\_add\_setting\_override\_table.py                                |       28 |        9 |        4 |        1 |     62% | 44, 87-96 |
| app/sep/migrations/versions/2026\_06\_01\_1530-e5c224619161\_add\_appstate\_table.py                                         |       14 |        2 |        0 |        0 |     86% |     53-54 |
| app/sep/migrations/versions/2026\_06\_02\_1512-378c0872642f\_extend\_setting\_class\_enum\_settings\_alert.py                |       23 |        8 |        4 |        1 |     59% | 47, 77-91 |
| app/sep/migrations/versions/2026\_06\_15\_1725-64f10ead74f6\_add\_seppluginperiodictask.py                                   |       16 |        3 |        0 |        0 |     81% |     55-57 |
| app/sep/migrations/versions/2026\_06\_16\_1200-a7c4e9f1b2d3\_add\_lifecycle\_state\_to\_app\_state.py                        |       26 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_16\_1600-b8d5f2a9c1e4\_add\_apprunningtask\_table.py                                   |       16 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_22\_1223-410eedfc5b43\_merge\_heads.py                                                 |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_22\_1400-c97e7e47c935\_extend\_setting\_class\_enum\_anonymizer.py                     |       23 |        8 |        4 |        1 |     59% | 47, 80-93 |
| app/sep/migrations/versions/2026\_06\_30\_1200-a1f4c7e9b2d3\_extend\_setting\_class\_enum\_alerts.py                         |       23 |        8 |        4 |        1 |     59% | 47, 82-95 |
| app/sep/migrations/versions/2026\_07\_02\_1000-f1a2b3c4d5e6\_merge\_heads\_before\_inventory\_settings.py                    |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_07\_02\_1001-a2b3c4d5e6f7\_extend\_setting\_class\_enum\_inventory.py                      |       25 |        2 |        4 |        2 |     86% |    59, 86 |
| app/sep/migrations/versions/2026\_08\_08\_0306-cf94cc04be4b\_drop\_session\_and\_messages\_setting\_.py                      |       30 |        3 |        6 |        3 |     83% |73, 106, 110 |
| app/sep/migrations/versions/2026\_08\_12\_1200-d1e2f3a4b5c6\_extend\_setting\_class\_enum\_health\_report.py                 |       25 |        2 |        4 |        2 |     86% |    59, 86 |
| app/sep/models.py                                                                                                            |       66 |        1 |        2 |        1 |     97% |       247 |
| app/sep/periodic\_tasks.py                                                                                                   |       55 |        0 |       20 |        0 |    100% |           |
| app/sep/routes/artifacts.py                                                                                                  |       38 |        1 |       14 |        1 |     96% |        87 |
| app/sep/routes/download\_files.py                                                                                            |       42 |        0 |        8 |        1 |     98% |   79-\>85 |
| app/sep/routes/execution\_events.py                                                                                          |       12 |        0 |        2 |        0 |    100% |           |
| app/sep/routes/stream\_logs.py                                                                                               |       77 |       23 |       12 |        4 |     67% |87-99, 106, 110-126, 128-133, 185-\>180, 191-196, 198-202 |
| app/sep/settings\_override.py                                                                                                |       43 |        0 |        2 |        0 |    100% |           |
| app/sep/snippets/builtin\_manifest.py                                                                                        |       26 |        0 |        6 |        0 |    100% |           |
| app/sep/snippets/celery.py                                                                                                   |       99 |        5 |       40 |        5 |     93% |83, 91-92, 201-\>208, 237, 263 |
| app/sep/snippets/checksums.py                                                                                                |       14 |        0 |        2 |        0 |    100% |           |
| app/sep/snippets/config.py                                                                                                   |      131 |       17 |       20 |        7 |     83% |127, 201-207, 220, 270, 352-357, 431-\>450, 438, 449, 465-468 |
| app/sep/snippets/constants.py                                                                                                |        1 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/crud.py                                                                                                     |       54 |        0 |       12 |        1 |     98% | 177-\>179 |
| app/sep/snippets/deps.py                                                                                                     |       87 |        8 |       26 |        2 |     88% |59, 130-132, 229, 261-268 |
| app/sep/snippets/list\_query.py                                                                                              |       15 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/masking.py                                                                                                  |      158 |        5 |       76 |        5 |     96% |156, 190, 192, 229-230, 321-\>316 |
| app/sep/snippets/models/constants.py                                                                                         |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/models/meta.py                                                                                              |      215 |        1 |       74 |        3 |     99% |537, 684-\>686, 686-\>688 |
| app/sep/snippets/models/responses.py                                                                                         |       28 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/models/snippet.py                                                                                           |      337 |        5 |       78 |        3 |     98% |208-\>231, 232-233, 638-640 |
| app/sep/snippets/schema.py                                                                                                   |       97 |        4 |       34 |        1 |     96% |157-159, 370 |
| app/sep/snippets/script\_source.py                                                                                           |       96 |        1 |       22 |        1 |     98% |       354 |
| app/sep/snippets/utils.py                                                                                                    |       32 |        0 |       10 |        0 |    100% |           |
| app/sep/sync/exceptions.py                                                                                                   |       25 |        0 |        0 |        0 |    100% |           |
| app/sep/sync/models.py                                                                                                       |      368 |       42 |      100 |       20 |     85% |81-90, 102-\>104, 104-\>106, 125, 131-\>133, 134-\>136, 195-\>201, 273-275, 304-\>302, 336, 396-397, 544, 592, 698-\>exit, 716, 730, 750-751, 786-\>exit, 831, 845, 867-868, 904-\>exit, 949, 962, 986-988, 1021-\>exit, 1130-\>exit, 1169, 1313-1315, 1422-1424, 1429-1435, 1439 |
| app/sep/sync/syncers/mysql/payload.py                                                                                        |      175 |       47 |       54 |        5 |     69% |156-\>164, 240-244, 249-254, 267-273, 277-300, 354-\>370, 373, 394-402, 421 |
| app/sep/sync/syncers/mysql/syncer.py                                                                                         |      222 |        1 |       86 |        8 |     97% |112, 268-\>270, 272-\>274, 586-\>594, 595-\>599, 676-\>687, 762-\>766, 764-\>763 |
| app/sep/sync/syncers/pmm.py                                                                                                  |       85 |       22 |       28 |        6 |     68% |78-82, 102-105, 116, 171-179, 227, 228-\>224, 231-247, 286-289, 303, 316 |
| app/sep/sync/syncers/system\_facts/payload.py                                                                                |      235 |       19 |       78 |       12 |     90% |52-\>58, 147-148, 176, 222-224, 231, 233-\>229, 244-251, 261-\>263, 263-\>265, 265-\>267, 282-284, 290-292, 316, 415-\>417, 417-\>419, 522, 533 |
| app/sep/sync/syncers/system\_facts/syncer.py                                                                                 |      118 |        7 |       28 |        3 |     93% |104, 169-170, 245, 256-\>254, 310-311, 350 |
| app/sep/tasks.py                                                                                                             |       31 |        0 |       12 |        2 |     95% |69-\>84, 73-\>76 |
| app/sep/utils/forms.py                                                                                                       |       20 |        0 |        6 |        0 |    100% |           |
| app/sep/utils/jinja.py                                                                                                       |       61 |       10 |       10 |        1 |     79% |105, 124, 135-140, 171-172 |
| app/tasks/alert\_hooks.py                                                                                                    |       23 |        0 |        2 |        0 |    100% |           |
| app/tasks/anonymizer/anonymize.py                                                                                            |       56 |        0 |       18 |        3 |     96% |75-\>82, 97-\>104, 118-\>122 |
| app/tasks/anonymizer/config.py                                                                                               |       30 |        1 |        6 |        1 |     94% |        77 |
| app/tasks/anonymizer/entities.py                                                                                             |       28 |        0 |        2 |        0 |    100% |           |
| app/tasks/celery.py                                                                                                          |      353 |       19 |       80 |        7 |     92% |255-\>267, 264-\>266, 461, 530-532, 705-\>741, 707-724, 875, 944, 967-968, 1069-\>1084 |
| app/tasks/config.py                                                                                                          |       41 |        0 |        2 |        0 |    100% |           |
| app/tasks/connectivity/constants.py                                                                                          |        5 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/models.py                                                                                             |       11 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/payload.py                                                                                            |       69 |        1 |        8 |        1 |     97% |       161 |
| app/tasks/connectivity/routes.py                                                                                             |       16 |        0 |        2 |        0 |    100% |           |
| app/tasks/connectivity/service.py                                                                                            |      146 |        2 |       54 |        6 |     96% |173, 432-\>431, 452-\>451, 458-\>457, 473, 485-\>484 |
| app/tasks/crud.py                                                                                                            |      272 |        5 |       74 |        6 |     97% |475-\>477, 478, 480, 605, 799, 801 |
| app/tasks/db/engine.py                                                                                                       |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/db/seed.py                                                                                                         |       73 |       25 |       24 |        3 |     59% |541-\>554, 555-\>569, 571-629, 658 |
| app/tasks/deps.py                                                                                                            |      110 |        3 |       30 |        0 |     98% |     64-66 |
| app/tasks/execution/exceptions.py                                                                                            |        8 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/celery/models.py                                                                               |       80 |        0 |       14 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/constants.py                                                                             |        1 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/exceptions.py                                                                            |        4 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/models.py                                                                                |      833 |       67 |      286 |       17 |     92% |175, 350, 368-371, 372-\>exit, 391, 434, 652, 714-\>716, 931-\>936, 940, 946, 982-987, 1078-\>1074, 1225-\>1240, 1445, 1536, 1929-1931, 1957-1958, 1995-1996, 2030-2031, 2077-\>2122, 2112-\>2077, 2346-2347, 2390, 2488-2489, 2563-2564, 2587-2643 |
| app/tasks/execution/executors/nomad/steps.py                                                                                 |       18 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/models.py                                                                                                |       68 |        0 |       14 |        0 |    100% |           |
| app/tasks/execution/nomad\_lifecycle.py                                                                                      |       54 |        0 |       12 |        2 |     97% |138-\>141, 180-\>exit |
| app/tasks/execution/utils.py                                                                                                 |       26 |        0 |        6 |        0 |    100% |           |
| app/tasks/hook\_resolver.py                                                                                                  |       29 |        0 |        6 |        0 |    100% |           |
| app/tasks/logs/constants.py                                                                                                  |        1 |        0 |        0 |        0 |    100% |           |
| app/tasks/logs/line\_split.py                                                                                                |       34 |        0 |        6 |        0 |    100% |           |
| app/tasks/logs/log\_reader.py                                                                                                |      140 |        8 |       62 |        6 |     92% |106, 131, 134, 181-194, 284, 294-\>286 |
| app/tasks/logs/log\_writer.py                                                                                                |      175 |       11 |       78 |       10 |     92% |145-146, 308-310, 376-377, 524, 528, 530-\>525, 532, 778, 784 |
| app/tasks/main.py                                                                                                            |       73 |        5 |       16 |        1 |     93% |209-210, 216-220 |
| app/tasks/migrations/env.py                                                                                                  |       36 |        5 |        4 |        2 |     82% |37-\>44, 64-75, 116 |
| app/tasks/migrations/versions/2024\_09\_18\_1542-04f50684d5d7\_create\_task\_and\_taskhistory\_tables.py                     |       34 |       12 |        0 |        0 |     65% |     77-88 |
| app/tasks/migrations/versions/2024\_10\_24\_1528-7920c0e4aa23\_update\_taskbackendenum.py                                    |       14 |        2 |        0 |        0 |     86% |     50-51 |
| app/tasks/migrations/versions/2024\_11\_16\_1508-d15d7ea76f80\_use\_enum\_for\_task\_owner.py                                |       16 |        3 |        0 |        0 |     81% |     50-55 |
| app/tasks/migrations/versions/2025\_05\_03\_1359-064c3cec8450\_update\_task\_owner\_enum.py                                  |       14 |        2 |        0 |        0 |     86% |     49-50 |
| app/tasks/migrations/versions/2025\_05\_03\_1454-80e592531cd7\_add\_started\_at\_and\_finished\_at\_fields\_.py              |       35 |       18 |       10 |        1 |     40% |61-69, 77-115 |
| app/tasks/migrations/versions/2025\_05\_15\_1933-bec093f02c15\_add\_field\_sync\_in\_progress\_started\_at\_.py              |       14 |        2 |        0 |        0 |     86% |     46-47 |
| app/tasks/migrations/versions/2025\_05\_20\_1144-68379e926e7c\_update\_taskhistory\_status\_enum.py                          |       14 |        2 |        0 |        0 |     86% |     50-51 |
| app/tasks/migrations/versions/2025\_05\_21\_1144-36f2b569e7bb\_create\_dispatchlock\_table.py                                |       14 |        2 |        0 |        0 |     86% |     52-53 |
| app/tasks/migrations/versions/2025\_06\_11\_1021-b4f0b7b50441\_add\_alert\_on\_fail\_field\_to\_task.py                      |       12 |        1 |        0 |        0 |     92% |        44 |
| app/tasks/migrations/versions/2025\_08\_05\_2350-19605d228fa3\_add\_anonymize\_mask\_field.py                                |       12 |        1 |        0 |        0 |     92% |        45 |
| app/tasks/migrations/versions/2025\_08\_07\_1757-8f61364b2c2c\_make\_task\_owner\_normal\_string.py                          |       14 |        2 |        0 |        0 |     86% |     46-47 |
| app/tasks/migrations/versions/2025\_08\_22\_2153-d39d37d3dcdc\_migrate\_legacy\_generatedtasks.py                            |      108 |       79 |       34 |        1 |     21% |59-62, 66-67, 71-74, 78-81, 85-113, 117-128, 155-166, 177, 214-221, 225-227, 231-255 |
| app/tasks/migrations/versions/2025\_09\_16\_1745-3b15a15ac473\_add\_anonymize\_mask\_field\_to\_taskhistory.py               |       16 |        3 |        0 |        0 |     81% |     49-51 |
| app/tasks/migrations/versions/2025\_09\_25\_0448-4e346919fc0f\_add\_output\_files\_path\_to\_task.py                         |       12 |        1 |        0 |        0 |     92% |        45 |
| app/tasks/migrations/versions/2025\_10\_07\_1752-0b852d9798ef\_add\_user\_tracking\_fields.py                                |       16 |        3 |        0 |        0 |     81% |     47-49 |
| app/tasks/migrations/versions/2025\_12\_29\_1001-add\_filelock\_requirement\_to\_backup\_tasks.py                            |       87 |       64 |       26 |        1 |     21% |54-73, 78-85, 105-136, 143-187 |
| app/tasks/migrations/versions/2026\_03\_04\_2149-bb3edb973603\_.py                                                           |       13 |        2 |        0 |        0 |     85% |     53-54 |
| app/tasks/migrations/versions/2026\_04\_14\_1000-taskhistory\_log\_create\_taskhistory\_log\_tables.py                       |       17 |        4 |        0 |        0 |     76% |   148-156 |
| app/tasks/migrations/versions/2026\_04\_14\_1752-9ebd648709e8\_add\_execution\_request\_json\_indexes.py                     |       27 |       12 |       12 |        2 |     44% |64-69, 73-\>exit, 85-94 |
| app/tasks/migrations/versions/2026\_04\_14\_2218-89e80a316a28\_convert\_execution\_request\_to\_jsonb.py                     |       18 |        7 |        4 |        1 |     55% |62-67, 74-78 |
| app/tasks/migrations/versions/2026\_04\_21\_1701-e42ce8324da7\_add\_stale\_to\_taskhistory\_status\_enum.py                  |       13 |        2 |        0 |        0 |     85% |     55-56 |
| app/tasks/migrations/versions/2026\_05\_18\_2014-fafdb0445092\_add\_setting\_override\_table.py                              |       28 |        9 |        4 |        1 |     62% | 44, 87-96 |
| app/tasks/migrations/versions/2026\_05\_20\_1500-7d1232c0e3ce\_coerce\_alters\_recursion\_method\_host.py                    |       37 |       15 |       10 |        1 |     49% |     75-91 |
| app/tasks/migrations/versions/2026\_06\_02\_1512-6d4cfd37bd3a\_extend\_setting\_class\_enum\_settings\_alert.py              |       23 |        8 |        4 |        1 |     59% | 47, 77-91 |
| app/tasks/migrations/versions/2026\_06\_22\_1223-2f5a00236369\_merge\_heads.py                                               |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_06\_22\_1400-abc65df0318a\_extend\_setting\_class\_enum\_anonymizer.py                   |       23 |        8 |        4 |        1 |     59% | 47, 80-93 |
| app/tasks/migrations/versions/2026\_06\_22\_1830-c4e8f0a3b1d2\_add\_alert\_detail\_builder\_to\_task.py                      |       14 |        1 |        0 |        0 |     93% |        60 |
| app/tasks/migrations/versions/2026\_06\_30\_1200-b2e5d8f0c3a4\_extend\_setting\_class\_enum\_alerts.py                       |       23 |        8 |        4 |        1 |     59% | 47, 82-95 |
| app/tasks/migrations/versions/2026\_06\_30\_1200-b7e1c0a4d9f2\_add\_taskhistory\_log\_retention\_index.py                    |       25 |        9 |        8 |        2 |     55% |65-66, 70-\>exit, 78-85 |
| app/tasks/migrations/versions/2026\_06\_30\_1838-fa5b80a1c8e0\_merge\_tasks\_migration\_heads.py                             |        9 |        1 |        0 |        0 |     89% |        38 |
| app/tasks/migrations/versions/2026\_06\_30\_1839-e3d856712405\_add\_taskhistory\_log\_stream\_end\_offset\_.py               |       23 |        8 |        4 |        1 |     59% |57-58, 67-74 |
| app/tasks/migrations/versions/2026\_06\_30\_1840-b74f05a17c8d\_rewrite\_persisted\_plugins\_module\_paths\_.py               |       36 |       19 |       16 |        1 |     35% |71-91, 101 |
| app/tasks/migrations/versions/2026\_07\_01\_1142-60bf743eb469\_add\_taskhistory\_log\_state\_nomad\_cursor\_.py              |       14 |        2 |        0 |        0 |     86% |     61-62 |
| app/tasks/migrations/versions/2026\_07\_01\_1142-f028a195fbda\_merge\_tasks\_migration\_heads.py                             |        9 |        1 |        0 |        0 |     89% |        38 |
| app/tasks/migrations/versions/2026\_07\_01\_1848-8657d05d27da\_merge\_tasks\_migration\_heads.py                             |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_07\_02\_1001-b3c4d5e6f7a8\_extend\_setting\_class\_enum\_inventory.py                    |       25 |        8 |        4 |        1 |     62% | 59, 81-91 |
| app/tasks/migrations/versions/2026\_07\_03\_1200-a1f4c9e2b7d8\_add\_taskhistory\_log\_allocation\_epoch.py                   |       11 |        1 |        0 |        0 |     91% |        57 |
| app/tasks/migrations/versions/2026\_07\_06\_1303-d25887ee3fea\_merge\_tasks\_migration\_heads.py                             |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_07\_06\_1900-13e897d11734\_relativize\_task\_payload\_refs.py                            |       48 |        2 |       16 |        2 |     94% |   74, 105 |
| app/tasks/migrations/versions/2026\_07\_25\_0217-27a11549ef43\_add\_run\_result\_recorder\_to\_task.py                       |       12 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_07\_30\_1300-c8e4a2b91f70\_rename\_log\_cursor\_columns\_executor\_neutral.py            |       24 |        1 |        4 |        1 |     93% |        64 |
| app/tasks/migrations/versions/2026\_08\_08\_0306-6a19d56d7985\_drop\_messages\_setting\_overrides.py                         |       27 |        9 |        6 |        1 |     58% | 61, 90-99 |
| app/tasks/migrations/versions/2026\_08\_12\_1200-e2f3a4b5c6d7\_extend\_setting\_class\_enum\_health\_report.py               |       25 |        2 |        4 |        2 |     86% |    59, 86 |
| app/tasks/migrations/versions/2026\_08\_13\_2143-a19da5cf0bca\_add\_taskhistory\_log\_state\_capture\_status.py              |       20 |        0 |        0 |        0 |    100% |           |
| app/tasks/models.py                                                                                                          |      346 |        4 |       68 |        5 |     98% |202, 645-\>648, 652, 667-\>673, 1177-\>1179, 1189-\>1191, 1214-1215 |
| app/tasks/periodic/crud.py                                                                                                   |       31 |        0 |        0 |        0 |    100% |           |
| app/tasks/periodic/deps.py                                                                                                   |       11 |        0 |        0 |        0 |    100% |           |
| app/tasks/periodic/models.py                                                                                                 |      111 |        5 |       34 |        5 |     93% |220, 255, 309, 325, 394 |
| app/tasks/periodic/routes.py                                                                                                 |       64 |        4 |       12 |        2 |     92% |91, 138-\>140, 160-163, 176 |
| app/tasks/periodic/utils.py                                                                                                  |       22 |        0 |        6 |        1 |     96% |   85-\>86 |
| app/tasks/routes.py                                                                                                          |      237 |       20 |       46 |        4 |     91% |153-157, 240-246, 279, 329-335, 342, 432, 475, 490, 650, 664, 672, 698, 706-\>708, 729-730 |
| app/tasks/run\_result.py                                                                                                     |       59 |        0 |       14 |        0 |    100% |           |
| app/tasks/settings/routes.py                                                                                                 |       13 |        0 |        0 |        0 |    100% |           |
| **TOTAL**                                                                                                                    | **26477** | **1665** | **6634** |  **620** | **92%** |           |


## Setup coverage badge

Below are examples of the badges you can use in your main branch `README` file.

### Direct image

[![Coverage badge](https://raw.githubusercontent.com/percona/SEP/python-coverage-comment-action-data/badge.svg)](https://htmlpreview.github.io/?https://github.com/percona/SEP/blob/python-coverage-comment-action-data/htmlcov/index.html)

This is the one to use if your repository is private or if you don't want to customize anything.

### [Shields.io](https://shields.io) Json Endpoint

[![Coverage badge](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/percona/SEP/python-coverage-comment-action-data/endpoint.json)](https://htmlpreview.github.io/?https://github.com/percona/SEP/blob/python-coverage-comment-action-data/htmlcov/index.html)

Using this one will allow you to [customize](https://shields.io/endpoint) the look of your badge.
It won't work with private repositories. It won't be refreshed more than once per five minutes.

### [Shields.io](https://shields.io) Dynamic Badge

[![Coverage badge](https://img.shields.io/badge/dynamic/json?color=brightgreen&label=coverage&query=%24.message&url=https%3A%2F%2Fraw.githubusercontent.com%2Fpercona%2FSEP%2Fpython-coverage-comment-action-data%2Fendpoint.json)](https://htmlpreview.github.io/?https://github.com/percona/SEP/blob/python-coverage-comment-action-data/htmlcov/index.html)

This one will always be the same color. It won't work for private repos. I'm not even sure why we included it.

## What is that?

This branch is part of the
[python-coverage-comment-action](https://github.com/marketplace/actions/python-coverage-comment)
GitHub Action. All the files in this branch are automatically generated and may be
overwritten at any moment.