# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/percona/SEP/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                                                                         |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------------------------------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| app/api/deps.py                                                                                                              |       93 |        0 |       24 |        0 |    100% |           |
| app/api/main.py                                                                                                              |        6 |        0 |        0 |        0 |    100% |           |
| app/api/routes/config.py                                                                                                     |        9 |        0 |        0 |        0 |    100% |           |
| app/api/routes/oauth.py                                                                                                      |       77 |        0 |       14 |        0 |    100% |           |
| app/api/routes/users.py                                                                                                      |       23 |        0 |        4 |        0 |    100% |           |
| app/celery.py                                                                                                                |       34 |        4 |        2 |        0 |     89% | 51, 57-59 |
| app/core/alerts/config.py                                                                                                    |       43 |        0 |        4 |        0 |    100% |           |
| app/core/alerts/models.py                                                                                                    |       57 |        0 |       10 |        0 |    100% |           |
| app/core/alerts/providers/pagerduty.py                                                                                       |       36 |        1 |        2 |        1 |     95% |110, 127-\>129 |
| app/core/auth/base.py                                                                                                        |       14 |        2 |        0 |        0 |     86% |    63, 81 |
| app/core/auth/config.py                                                                                                      |       79 |        2 |       22 |        2 |     96% |  118, 161 |
| app/core/auth/exceptions.py                                                                                                  |       11 |        0 |        0 |        0 |    100% |           |
| app/core/auth/models.py                                                                                                      |       94 |        0 |        2 |        0 |    100% |           |
| app/core/auth/providers/casdoor/models.py                                                                                    |       95 |        6 |       18 |        1 |     90% |229-235, 265 |
| app/core/auth/providers/casdoor/provider.py                                                                                  |       14 |        0 |        0 |        0 |    100% |           |
| app/core/auth/providers/casdoor/sdk.py                                                                                       |      123 |       51 |       26 |        3 |     54% |51, 106-107, 118, 145-\>147, 161-170, 190-191, 210-217, 243-265, 273, 292-300, 316-319, 355-\>354, 373-378, 386-387, 400, 410-416, 426-432 |
| app/core/auth/providers/grafana/models.py                                                                                    |      187 |        4 |       40 |        2 |     97% |375, 659, 680-681 |
| app/core/auth/providers/grafana/provider.py                                                                                  |       25 |        0 |        4 |        0 |    100% |           |
| app/core/auth/providers/grafana/sdk.py                                                                                       |       54 |        0 |        6 |        0 |    100% |           |
| app/core/auth/utils.py                                                                                                       |        6 |        1 |        0 |        0 |     83% |        35 |
| app/core/celery/bootstrap.py                                                                                                 |       31 |        2 |        2 |        1 |     91% |  141, 145 |
| app/core/celery/config.py                                                                                                    |       34 |        0 |        2 |        0 |    100% |           |
| app/core/celery/crud.py                                                                                                      |       26 |        2 |        4 |        1 |     90% |     91-97 |
| app/core/celery/db.py                                                                                                        |        8 |        0 |        0 |        0 |    100% |           |
| app/core/celery/deps.py                                                                                                      |       10 |        0 |        0 |        0 |    100% |           |
| app/core/celery/models.py                                                                                                    |       43 |        2 |        8 |        2 |     92% |   78, 177 |
| app/core/celery/utils.py                                                                                                     |       35 |        0 |       12 |        0 |    100% |           |
| app/core/config.py                                                                                                           |      275 |        7 |       54 |        6 |     96% |258-\>exit, 335, 597, 775, 855, 931, 944, 982-\>984, 987 |
| app/core/db/config.py                                                                                                        |       36 |        0 |        6 |        0 |    100% |           |
| app/core/db/crud.py                                                                                                          |      290 |        8 |       80 |        8 |     96% |250, 343-\>345, 345-\>347, 347-\>349, 356-\>372, 442, 589-592, 1001, 1005, 1185-\>1179, 1295-1296 |
| app/core/db/deps.py                                                                                                          |        8 |        0 |        0 |        0 |    100% |           |
| app/core/db/in\_memory\_list\_query.py                                                                                       |       73 |        0 |       14 |        0 |    100% |           |
| app/core/db/list\_query.py                                                                                                   |       87 |        0 |       24 |        0 |    100% |           |
| app/core/db/models.py                                                                                                        |       14 |        0 |        0 |        0 |    100% |           |
| app/core/db/sql\_types.py                                                                                                    |       37 |        0 |       12 |        0 |    100% |           |
| app/core/db/utils.py                                                                                                         |       94 |        5 |       28 |        5 |     92% |109, 259, 288, 291, 309 |
| app/core/encryption.py                                                                                                       |       26 |        0 |        0 |        0 |    100% |           |
| app/core/exceptions.py                                                                                                       |       26 |        0 |        0 |        0 |    100% |           |
| app/core/health.py                                                                                                           |       79 |        0 |       12 |        0 |    100% |           |
| app/core/log.py                                                                                                              |       41 |        0 |       16 |        0 |    100% |           |
| app/core/middleware/log\_context.py                                                                                          |       26 |        0 |        2 |        0 |    100% |           |
| app/core/middleware/security\_headers.py                                                                                     |      105 |        0 |       20 |        1 |     99% |221-\>exit |
| app/core/models.py                                                                                                           |       20 |        0 |        2 |        0 |    100% |           |
| app/core/pagination/deps.py                                                                                                  |       17 |        0 |        2 |        0 |    100% |           |
| app/core/pagination/models.py                                                                                                |       78 |        1 |       20 |        1 |     98% |        77 |
| app/core/pmm.py                                                                                                              |       51 |        1 |       10 |        1 |     97% |        53 |
| app/core/requests/connectivity.py                                                                                            |       33 |        0 |        8 |        0 |    100% |           |
| app/core/requests/registry.py                                                                                                |       64 |        5 |       22 |        5 |     88% |101, 112, 158, 169, 179 |
| app/core/requests/remote\_api.py                                                                                             |      314 |        1 |       68 |        2 |     99% |337, 807-\>806 |
| app/core/security.py                                                                                                         |       18 |        0 |        4 |        0 |    100% |           |
| app/core/settings\_override/alembic\_ops.py                                                                                  |       39 |        5 |       12 |        6 |     78% |56, 59, 61, 63-\>65, 84, 86 |
| app/core/settings\_override/api/export.py                                                                                    |        9 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/api/models.py                                                                                    |       21 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/api/routes.py                                                                                    |      306 |       33 |      100 |        8 |     87% |322, 456, 480, 610-617, 744, 773-783, 817-823, 831, 955, 985, 1124, 1126, 1128, 1151, 1359-\>1390, 1367-1376, 1380-1389 |
| app/core/settings\_override/cache.py                                                                                         |      117 |       13 |       46 |        6 |     86% |188-193, 206-211, 288, 351, 392, 396-403 |
| app/core/settings\_override/constants.py                                                                                     |        3 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/lifecycle.py                                                                                     |       94 |        2 |       24 |        1 |     97% |   63, 356 |
| app/core/settings\_override/manager.py                                                                                       |        5 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/models.py                                                                                        |       47 |        3 |        8 |        3 |     89% |117, 119, 183 |
| app/core/settings\_override/policy.py                                                                                        |       29 |        0 |        6 |        0 |    100% |           |
| app/core/settings\_override/proxy.py                                                                                         |       21 |        0 |        2 |        0 |    100% |           |
| app/core/settings\_override/registry.py                                                                                      |      642 |       47 |      328 |       29 |     91% |835, 978, 1031, 1065, 1080, 1138, 1355, 1415, 1480-1481, 1485, 1486-\>1472, 1487-\>1486, 1517, 1522, 1559, 1588, 1607, 1706, 1711, 1737, 1765-\>1760, 1788-1794, 1825, 1828, 1855-1856, 1870-1880, 1907-1910, 1916-\>1919, 1922, 1926-1929, 2055 |
| app/core/settings\_override/worker.py                                                                                        |       28 |        0 |        6 |        0 |    100% |           |
| app/core/utils/async\_run.py                                                                                                 |       13 |        0 |        0 |        0 |    100% |           |
| app/core/utils/cache.py                                                                                                      |       93 |        5 |       16 |        4 |     90% |60-62, 147-\>153, 151, 187-\>192, 224 |
| app/core/utils/cli\_args.py                                                                                                  |       12 |        0 |        0 |        0 |    100% |           |
| app/core/utils/date\_time.py                                                                                                 |        8 |        0 |        2 |        0 |    100% |           |
| app/core/utils/dict.py                                                                                                       |       29 |        4 |       12 |        0 |     85% |   165-168 |
| app/core/utils/fields.py                                                                                                     |      230 |        7 |       30 |        5 |     95% |174, 246-247, 393, 397, 618, 666 |
| app/core/utils/imports.py                                                                                                    |       28 |        0 |        8 |        0 |    100% |           |
| app/core/utils/iterators.py                                                                                                  |       18 |        0 |        6 |        0 |    100% |           |
| app/core/utils/json\_pointer.py                                                                                              |       41 |        0 |       22 |        0 |    100% |           |
| app/core/utils/lazy.py                                                                                                       |       31 |        0 |        4 |        0 |    100% |           |
| app/core/utils/openapi.py                                                                                                    |      246 |        5 |      120 |        7 |     96% |141, 513, 515-\>514, 520-521, 564-\>566, 583-\>582, 600 |
| app/core/utils/path.py                                                                                                       |       40 |        0 |       14 |        0 |    100% |           |
| app/core/utils/pydantic.py                                                                                                   |       74 |        0 |       22 |        0 |    100% |           |
| app/core/utils/serialization.py                                                                                              |        7 |        0 |        0 |        0 |    100% |           |
| app/core/utils/strings.py                                                                                                    |       24 |        1 |        4 |        1 |     93% |        65 |
| app/inventory/config.py                                                                                                      |       12 |        0 |        0 |        0 |    100% |           |
| app/inventory/constants.py                                                                                                   |       15 |        0 |        0 |        0 |    100% |           |
| app/inventory/crud.py                                                                                                        |      386 |        6 |       72 |        3 |     98% |338, 506-508, 782-\>784, 969, 1297, 1821-\>exit |
| app/inventory/db.py                                                                                                          |        6 |        0 |        0 |        0 |    100% |           |
| app/inventory/deps.py                                                                                                        |       63 |        9 |        4 |        0 |     81% |63-65, 272-274, 293-295 |
| app/inventory/main.py                                                                                                        |       44 |        6 |        2 |        1 |     85% |52, 97-98, 136-140 |
| app/inventory/migrations/env.py                                                                                              |       35 |        5 |        4 |        2 |     82% |36-\>43, 64-75, 117 |
| app/inventory/migrations/versions/2024\_09\_24\_1701-8e95b4982efb\_create\_inventory\_tables.py                              |       36 |       13 |        0 |        0 |     64% |    96-108 |
| app/inventory/migrations/versions/2024\_10\_15\_1724-6761fa809e84\_create\_unique\_index\_for\_service\_port\_by\_.py        |       12 |        1 |        0 |        0 |     92% |        45 |
| app/inventory/migrations/versions/2024\_11\_25\_0946-83707159e945\_add\_keys\_field\_for\_table.py                           |       12 |        1 |        0 |        0 |     92% |        45 |
| app/inventory/migrations/versions/2025\_02\_13\_2052-b422e3cb9b35\_force\_create\_to\_text.py                                |       14 |        2 |        0 |        0 |     86% |     49-50 |
| app/inventory/migrations/versions/2025\_02\_14\_1806-4df7d4433322\_update\_servicetypeenum.py                                |       14 |        2 |        0 |        0 |     86% |     51-52 |
| app/inventory/migrations/versions/2025\_07\_10\_1811-2f39f63eb355\_make\_servicetypeenum\_non\_native.py                     |       14 |        2 |        0 |        0 |     86% |     50-51 |
| app/inventory/migrations/versions/2025\_10\_03\_1531-ceea7494ff83\_add\_new\_pmm\_service\_fields.py                         |       16 |        3 |        0 |        0 |     81% |     47-49 |
| app/inventory/migrations/versions/2026\_06\_04\_1005-b73c0110ad55\_add\_system\_observation\_tables.py                       |       18 |        4 |        0 |        0 |     78% |     80-89 |
| app/inventory/migrations/versions/2026\_07\_02\_1000-c4d5e6f7a8b9\_add\_setting\_override\_table.py                          |       29 |        9 |        4 |        1 |     64% |63, 103-112 |
| app/inventory/migrations/versions/2026\_08\_08\_0306-34e6108ea194\_drop\_messages\_setting\_overrides.py                     |       27 |        9 |        6 |        1 |     58% | 61, 90-99 |
| app/inventory/migrations/versions/2026\_08\_12\_1200-f3a4b5c6d7e8\_extend\_setting\_class\_enum\_health\_report.py           |       27 |        9 |        6 |        2 |     61% |63, 67, 89-99 |
| app/inventory/migrations/versions/2026\_08\_17\_2210-a38607bba456\_drop\_setting\_class\_check\_constraint.py                |        9 |        1 |        0 |        0 |     89% |        50 |
| app/inventory/migrations/versions/2026\_08\_26\_1030-c7d1e94ab3f2\_add\_retirement\_columns\_to\_inventory\_.py              |       25 |        9 |       10 |        0 |     57% |     89-97 |
| app/inventory/migrations/versions/2026\_08\_26\_1730-e4b8c2f7a915\_require\_pmm\_origin\_on\_inventory\_entities.py          |       38 |        0 |        6 |        0 |    100% |           |
| app/inventory/migrations/versions/2026\_08\_26\_1800-d4f2a7c8b1e6\_add\_retirement\_collection\_indexes.py                   |       28 |        6 |       16 |        4 |     68% |74-76, 81-\>exit, 93-95, 98-\>exit |
| app/inventory/migrations/versions/2026\_08\_27\_1655-7ac8bc62f65d\_drop\_narrowed\_service\_port\_uniqueness\_.py            |       13 |        0 |        0 |        0 |    100% |           |
| app/inventory/migrations/versions/2026\_08\_28\_1528-5c93a28faa5f\_merge\_d4f2a7c8b1e6\_7ac8bc62f65d.py                      |       12 |        0 |        0 |        0 |    100% |           |
| app/inventory/migrations/versions/2026\_08\_28\_2104-3c39abf7a429\_add\_identity\_alias\_tables.py                           |       22 |        0 |        0 |        0 |    100% |           |
| app/inventory/migrations/versions/2026\_08\_31\_2200-9f2c14d6b8a7\_add\_sync\_health\_columns\_to\_inventory\_.py            |       18 |        0 |        6 |        0 |    100% |           |
| app/inventory/models.py                                                                                                      |      150 |        0 |        8 |        0 |    100% |           |
| app/inventory/routes/collection.py                                                                                           |       23 |        7 |        6 |        1 |     59% |73-74, 76-80 |
| app/inventory/routes/nodes.py                                                                                                |       74 |        2 |        4 |        0 |     95% |  285, 287 |
| app/inventory/routes/schemas.py                                                                                              |       42 |        0 |        0 |        0 |    100% |           |
| app/inventory/routes/services.py                                                                                             |       74 |        3 |        6 |        0 |     91% |247, 249, 285 |
| app/inventory/routes/tables.py                                                                                               |       34 |        0 |        0 |        0 |    100% |           |
| app/inventory/settings/routes.py                                                                                             |       12 |        0 |        0 |        0 |    100% |           |
| app/main.py                                                                                                                  |       91 |       23 |        6 |        1 |     73% |   252-306 |
| app/sep/api/constants.py                                                                                                     |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/api/host\_resolution.py                                                                                              |        9 |        0 |        4 |        0 |    100% |           |
| app/sep/api/models.py                                                                                                        |       14 |        0 |        0 |        0 |    100% |           |
| app/sep/api/openapi.py                                                                                                       |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/api/proxy.py                                                                                                         |       16 |        0 |        2 |        0 |    100% |           |
| app/sep/api/router.py                                                                                                        |       39 |        0 |        4 |        0 |    100% |           |
| app/sep/api/routes/app\_info.py                                                                                              |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/app\_state.py                                                                                             |       44 |       12 |       10 |        2 |     59% |180, 186, 188-195, 202, 208-209, 237-238, 243-244, 251 |
| app/sep/api/routes/apps.py                                                                                                   |       22 |        3 |        2 |        1 |     83% |87, 107-108 |
| app/sep/api/routes/connectivity\_check.py                                                                                    |       75 |        0 |       24 |        0 |    100% |           |
| app/sep/api/routes/dashboard.py                                                                                              |       35 |        0 |        6 |        0 |    100% |           |
| app/sep/api/routes/hosts.py                                                                                                  |       22 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/periodic\_tasks.py                                                                                        |       30 |        0 |        2 |        0 |    100% |           |
| app/sep/api/routes/schemas.py                                                                                                |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/services.py                                                                                               |       17 |        0 |        2 |        0 |    100% |           |
| app/sep/api/routes/settings.py                                                                                               |      129 |        6 |       50 |        3 |     94% |131, 136, 291-293, 321 |
| app/sep/api/routes/task\_history.py                                                                                          |       28 |        0 |        4 |        0 |    100% |           |
| app/sep/api/routes/task\_stats.py                                                                                            |       14 |        0 |        0 |        0 |    100% |           |
| app/sep/api/task\_history\_merge.py                                                                                          |       55 |        4 |       16 |        3 |     90% |57, 61-62, 113, 115-\>117 |
| app/sep/app\_drain.py                                                                                                        |       83 |        2 |       14 |        2 |     96% |137-\>139, 208, 216 |
| app/sep/apps/alert\_troubleshooting/api\_routes.py                                                                           |       23 |        4 |        2 |        0 |     76% |64-65, 73-80 |
| app/sep/apps/alert\_troubleshooting/app.py                                                                                   |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alert\_troubleshooting/deps.py                                                                                  |      108 |        4 |       44 |        3 |     95% |107, 109-\>111, 222, 235, 319 |
| app/sep/apps/alert\_troubleshooting/models.py                                                                                |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alert\_troubleshooting/schema.py                                                                                |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/api\_routes.py                                                                                           |      124 |       16 |       16 |        0 |     86% |178, 194-197, 242-252 |
| app/sep/apps/alerts/app.py                                                                                                   |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/app\_owned\_settings.py                                                                                  |        3 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/celery.py                                                                                                |       46 |        1 |       10 |        0 |     98% |        39 |
| app/sep/apps/alerts/config.py                                                                                                |       13 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/crud.py                                                                                                  |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/deps.py                                                                                                  |       75 |        0 |       16 |        0 |    100% |           |
| app/sep/apps/alerts/loader.py                                                                                                |       22 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/alerts/migrations/versions/2026\_04\_20\_1817-d21ad387df7a\_create\_alert\_backup\_table.py                     |       14 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/alerts/models.py                                                                                                |       46 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/restore.py                                                                                               |       95 |        0 |       26 |        0 |    100% |           |
| app/sep/apps/alters/api\_routes.py                                                                                           |       38 |        3 |        0 |        0 |     92% |82, 140-145 |
| app/sep/apps/alters/app.py                                                                                                   |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alters/deps.py                                                                                                  |      209 |       12 |       62 |       11 |     92% |98, 128-\>140, 134-\>133, 138-\>133, 141, 344, 411-412, 468, 551, 574-575, 695, 706, 708, 747-\>751 |
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
| app/sep/apps/atw/api\_routes.py                                                                                              |      232 |       48 |       40 |        3 |     77% |208-\>218, 267, 285, 300, 325, 399-400, 404-410, 473-486, 488-504, 513, 515-531, 551-553, 736-\>743, 737, 793-799, 801-804, 822, 840, 879 |
| app/sep/apps/atw/app.py                                                                                                      |       12 |        1 |        2 |        1 |     86% |        47 |
| app/sep/apps/atw/batch.py                                                                                                    |       74 |        0 |        8 |        0 |    100% |           |
| app/sep/apps/atw/categories.py                                                                                               |       34 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/atw/celery.py                                                                                                   |       18 |        5 |        2 |        0 |     65% | 42, 54-57 |
| app/sep/apps/atw/config.py                                                                                                   |       15 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/crud.py                                                                                                     |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/deps.py                                                                                                     |       37 |        0 |        8 |        0 |    100% |           |
| app/sep/apps/atw/migrations/versions/2026\_07\_20\_1238-b82887dfe93d\_create\_atw\_incident\_tables.py                       |       24 |        7 |        8 |        2 |     59% |40-\>55, 55-\>exit, 85-94 |
| app/sep/apps/atw/migrations/versions/2026\_07\_24\_1100-c93998e0fa14\_create\_atw\_send\_log\_table.py                       |       20 |        5 |        4 |        1 |     67% |40-\>exit, 81-87 |
| app/sep/apps/atw/migrations/versions/2026\_07\_30\_1200-447ee0172734\_add\_atw\_incident\_closed\_at.py                      |       25 |        2 |        8 |        4 |     82% |41, 43-\>exit, 55, 57-\>exit |
| app/sep/apps/atw/models.py                                                                                                   |       62 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/schema.py                                                                                                   |       13 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/atw/send.py                                                                                                     |      278 |        6 |       52 |        0 |     98% |112, 168, 180, 497, 869-870 |
| app/sep/apps/backup\_mongo/api\_routes.py                                                                                    |       30 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/app.py                                                                                            |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/deps.py                                                                                           |      116 |       14 |       18 |        0 |     84% |   241-260 |
| app/sep/apps/backup\_mongo/models.py                                                                                         |      239 |        0 |       42 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/pbm\_creds\_common.py                                                                             |      159 |        3 |       32 |        1 |     98% |83-\>92, 147-149 |
| app/sep/apps/backup\_mongo/restore/api\_routes.py                                                                            |       34 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/app.py                                                                                    |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/deps.py                                                                                   |      139 |        7 |       18 |        2 |     94% |180, 424-440, 455 |
| app/sep/apps/backup\_mongo/restore/models.py                                                                                 |      159 |        7 |       22 |        5 |     93% |79-81, 83, 86-90, 302-\>306, 340-\>342, 640 |
| app/sep/apps/backup\_mongo/restore/schema.py                                                                                 |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/spec.py                                                                                   |       31 |        2 |        0 |        0 |     94% |   190-191 |
| app/sep/apps/backup\_mongo/restore/views.py                                                                                  |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/schema.py                                                                                         |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/spec.py                                                                                           |       51 |        3 |       24 |        4 |     91% |78, 87-\>90, 131, 136 |
| app/sep/apps/backup\_mongo/views.py                                                                                          |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/app.py                                                                                               |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/deps.py                                                                                              |       58 |        6 |       10 |        1 |     90% |58-59, 62, 98-100 |
| app/sep/apps/backup\_pg/form\_backfill.py                                                                                    |       46 |        4 |       16 |        4 |     87% |44-\>57, 47-48, 49-\>57, 51-\>57, 53-\>57, 85-86 |
| app/sep/apps/backup\_pg/models.py                                                                                            |       48 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/spec.py                                                                                              |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/views.py                                                                                             |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/checksums/app.py                                                                                                |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/checksums/deps.py                                                                                               |       18 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/checksums/form\_backfill.py                                                                                     |       48 |        4 |       24 |        5 |     88% |55, 63, 70, 91, 109-\>108 |
| app/sep/apps/checksums/models.py                                                                                             |       75 |        4 |       20 |        4 |     92% |55, 57, 60, 315 |
| app/sep/apps/checksums/spec.py                                                                                               |       68 |        0 |       26 |        2 |     98% |115-\>123, 190-\>192 |
| app/sep/apps/checksums/views.py                                                                                              |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/api\_routes.py                                                                                           |       67 |        4 |        4 |        1 |     93% |83-84, 140-141 |
| app/sep/apps/dipper/app.py                                                                                                   |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/constants.py                                                                                             |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/deps.py                                                                                                  |      120 |       14 |       34 |        8 |     83% |120-122, 143-144, 184-187, 188-\>195, 218, 219-\>221, 278, 280, 282, 391 |
| app/sep/apps/dipper/models.py                                                                                                |       17 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/dipper/schema.py                                                                                                |       36 |        1 |       10 |        1 |     96% |       238 |
| app/sep/apps/field\_names.py                                                                                                 |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/framework/api.py                                                                                                |      332 |       10 |      130 |        8 |     96% |142-\>140, 197-202, 724, 731, 859, 865, 870, 876, 891, 1300 |
| app/sep/apps/framework/apps.py                                                                                               |      342 |        7 |      138 |        7 |     97% |539, 703, 719, 736, 796, 810, 817 |
| app/sep/apps/framework/base.py                                                                                               |       45 |        2 |        6 |        2 |     92% |  166, 173 |
| app/sep/apps/framework/cascade.py                                                                                            |      189 |        0 |       62 |        2 |     99% |131-\>133, 147-\>149 |
| app/sep/apps/framework/conformance.py                                                                                        |      100 |        9 |       52 |        7 |     88% |69, 174, 200-204, 268, 281, 285, 333 |
| app/sep/apps/framework/connectivity.py                                                                                       |       25 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/framework/deps.py                                                                                               |       15 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/framework/form\_backfill.py                                                                                     |      201 |       38 |       34 |        4 |     80% |122, 127, 132, 137, 142, 147, 323-329, 355-361, 364-369, 389-395, 398, 482-\>489, 511-552, 641 |
| app/sep/apps/framework/form\_backfill\_guards.py                                                                             |       10 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/framework/form\_backfill\_inventory.py                                                                          |      141 |       10 |       52 |       12 |     89% |71, 76-\>exit, 144, 147, 151, 164-\>142, 196, 199-\>212, 216, 249, 267, 280-281, 317-\>323 |
| app/sep/apps/framework/form\_backfill\_registry.py                                                                           |       47 |        0 |       14 |        0 |    100% |           |
| app/sep/apps/framework/form\_dsl/conformance.py                                                                              |       46 |        9 |       18 |        3 |     75% |65, 69, 85-93 |
| app/sep/apps/framework/form\_dsl/derivation.py                                                                               |      350 |       22 |      178 |       23 |     91% |258, 275, 451, 472, 479, 485-\>481, 494, 504-\>510, 507-509, 523-\>525, 528, 530-\>525, 532, 549, 555, 570, 573, 581, 587-588, 590, 641, 647, 841 |
| app/sep/apps/framework/form\_dsl/markers.py                                                                                  |      122 |        1 |       14 |        1 |     99% |       189 |
| app/sep/apps/framework/form\_dsl/model.py                                                                                    |       17 |        1 |        2 |        1 |     89% |        70 |
| app/sep/apps/framework/form\_dsl/pt\_toolkit.py                                                                              |       56 |        0 |       26 |        0 |    100% |           |
| app/sep/apps/framework/inventory\_references.py                                                                              |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/framework/list\_query.py                                                                                        |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/framework/registry.py                                                                                           |      196 |        3 |      106 |        3 |     98% |416, 418, 437 |
| app/sep/apps/framework/responses.py                                                                                          |       96 |        1 |       20 |        1 |     98% |        64 |
| app/sep/apps/framework/rules.py                                                                                              |      538 |        7 |      130 |        5 |     98% |323, 328, 333, 545, 861, 1348, 1368 |
| app/sep/apps/framework/scaffold.py                                                                                           |      429 |       29 |      150 |       20 |     91% |281, 292, 304, 421, 516, 519, 539-\>546, 542, 593-595, 629, 670, 674, 874, 1103-1106, 1132, 1134, 1148-1151, 1177, 1182-1185, 1204, 1244 |
| app/sep/apps/framework/schema.py                                                                                             |      404 |        2 |      122 |        2 |     99% |1337, 1813 |
| app/sep/apps/framework/script\_helpers.py                                                                                    |       44 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/framework/script\_source.py                                                                                     |       63 |        0 |       14 |        0 |    100% |           |
| app/sep/apps/framework/spec.py                                                                                               |      151 |        0 |       68 |        0 |    100% |           |
| app/sep/apps/framework/task\_status.py                                                                                       |       45 |        0 |       14 |        0 |    100% |           |
| app/sep/apps/inventory/api\_routes.py                                                                                        |       39 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/app.py                                                                                                |       10 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/app\_owned\_settings.py                                                                               |        3 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/collection.py                                                                                         |      100 |        3 |       26 |        0 |     98% |   325-327 |
| app/sep/apps/inventory/config.py                                                                                             |       16 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/connectivity.py                                                                                       |       42 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/inventory/constants.py                                                                                          |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/inventory/deps.py                                                                                               |       68 |        8 |       14 |        0 |     88% |264, 284-302 |
| app/sep/apps/inventory/models.py                                                                                             |       31 |        7 |        8 |        3 |     69% |109, 111, 112-\>114, 130-138 |
| app/sep/apps/inventory/sync.py                                                                                               |       30 |        0 |       12 |        0 |    100% |           |
| app/sep/apps/labels.py                                                                                                       |        1 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/meta\_keys.py                                                                                                   |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/api\_routes.py                                                                                   |       19 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/app.py                                                                                           |       14 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/backup\_source\_choices.py                                                                       |       62 |       11 |       24 |        1 |     77% |   148-158 |
| app/sep/apps/mysql\_backups/crud.py                                                                                          |       22 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/deps.py                                                                                          |       82 |        0 |       22 |        1 |     99% | 285-\>288 |
| app/sep/apps/mysql\_backups/form\_backfill.py                                                                                |       62 |        6 |       22 |        7 |     85% |83-\>105, 86-87, 88-\>105, 90-\>105, 92-\>105, 96-\>105, 99, 129-130, 140 |
| app/sep/apps/mysql\_backups/forms.py                                                                                         |      213 |        3 |       18 |        3 |     97% |787, 802, 820 |
| app/sep/apps/mysql\_backups/inventory\_references.py                                                                         |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/migrations/versions/2026\_07\_29\_1200-f0a1b2c3d4e5\_create\_mysql\_backup\_run\_table.py        |       22 |        6 |        4 |        1 |     65% |40-\>exit, 89-98 |
| app/sep/apps/mysql\_backups/migrations/versions/2026\_08\_06\_1200-b7c8d9e0f1a2\_add\_service\_id\_to\_mysql\_backup\_run.py |       30 |        0 |       12 |        2 |     95% |66-\>exit, 74-\>exit |
| app/sep/apps/mysql\_backups/models.py                                                                                        |       50 |        0 |        4 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/payload\_variants.py                                                                             |       13 |        0 |        4 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/recorder.py                                                                                      |       43 |        0 |       10 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/restore/app.py                                                                                   |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/restore/deps.py                                                                                  |       79 |       14 |       20 |        5 |     79% |68, 81-\>85, 102-113, 152-153, 157, 162, 165-166 |
| app/sep/apps/mysql\_backups/restore/form\_backfill.py                                                                        |       55 |        3 |       18 |        1 |     95% |127-128, 141 |
| app/sep/apps/mysql\_backups/restore/models.py                                                                                |      141 |        2 |       14 |        2 |     97% |   52, 477 |
| app/sep/apps/mysql\_backups/restore/spec.py                                                                                  |       35 |        1 |        8 |        1 |     95% |       106 |
| app/sep/apps/mysql\_backups/restore/views.py                                                                                 |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/spec.py                                                                                          |       32 |        1 |       10 |        1 |     95% |       135 |
| app/sep/apps/mysql\_backups/views.py                                                                                         |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/nav\_icons.py                                                                                                   |       16 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/report/api\_routes.py                                                                                           |       68 |        2 |       18 |        3 |     94% |80, 86-\>90, 195-\>197, 231 |
| app/sep/apps/report/app.py                                                                                                   |       26 |        3 |       14 |        6 |     78% |47-\>49, 50, 51-\>53, 54, 56, 57-\>59 |
| app/sep/apps/report/app\_owned\_settings.py                                                                                  |        3 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/report/artifact\_store.py                                                                                       |       45 |        2 |       10 |        0 |     96% |   149-150 |
| app/sep/apps/report/celery.py                                                                                                |       82 |       19 |       12 |        3 |     74% |87-89, 118-119, 150, 224-226, 229, 232-233, 236-241, 263-267 |
| app/sep/apps/report/config.py                                                                                                |       70 |        5 |       18 |        5 |     89% |137, 151, 155, 157, 159 |
| app/sep/apps/report/deps.py                                                                                                  |        1 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/report/job\_service.py                                                                                          |        8 |        1 |        2 |        0 |     90% |        43 |
| app/sep/apps/report/models.py                                                                                                |      117 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/report/service.py                                                                                               |      379 |       16 |      128 |       14 |     94% |144, 148, 349, 363-364, 425, 462-463, 465, 469, 470-\>473, 571, 576, 578-\>568, 584, 593, 656, 663 |
| app/sep/apps/shared/backups/columns.py                                                                                       |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/shared/backups/edit\_form.py                                                                                    |       17 |        0 |       10 |        0 |    100% |           |
| app/sep/apps/shared/backups/responses.py                                                                                     |        3 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/shared/disk\_script\_source.py                                                                                  |       82 |        2 |       18 |        2 |     96% |  214, 259 |
| app/sep/apps/snippets/app.py                                                                                                 |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/snippets/extra\_routes.py                                                                                       |       71 |        6 |       10 |        0 |     93% |80-82, 99, 183, 214 |
| app/sep/apps/tasks/api\_routes.py                                                                                            |       28 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/tasks/app.py                                                                                                    |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/tasks/deps.py                                                                                                   |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/tasks/models.py                                                                                                 |       29 |        1 |        2 |        1 |     94% |       115 |
| app/sep/apps/tasks/schema.py                                                                                                 |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/topology/api\_routes.py                                                                                         |      138 |       13 |       44 |       11 |     87% |91, 120-\>118, 139, 147, 202, 223, 229, 236-\>226, 240, 280, 283-285, 286-\>276, 302-303 |
| app/sep/apps/topology/app.py                                                                                                 |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/topology/models.py                                                                                              |      112 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/topology/topology.py                                                                                            |      173 |        7 |       58 |        8 |     94% |118-119, 122-\>114, 153, 156-157, 226-\>228, 229-\>231, 407, 491-\>501, 505 |
| app/sep/artifact\_constants.py                                                                                               |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/bundle\_upload/factory.py                                                                                            |       30 |        1 |        4 |        1 |     94% |        67 |
| app/sep/bundle\_upload/plan.py                                                                                               |      271 |        2 |       82 |        2 |     99% | 895, 1039 |
| app/sep/bundle\_upload/resolver.py                                                                                           |       56 |        0 |       14 |        0 |    100% |           |
| app/sep/bundle\_upload/seam.py                                                                                               |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/clients/pmm.py                                                                                                       |      292 |        2 |       74 |        3 |     99% |565, 567, 980-\>982 |
| app/sep/config.py                                                                                                            |      229 |        4 |       54 |        4 |     97% |179, 228, 404, 712 |
| app/sep/connectivity.py                                                                                                      |       39 |        4 |        2 |        1 |     88% |84, 163-169 |
| app/sep/crud.py                                                                                                              |      140 |        0 |       24 |        0 |    100% |           |
| app/sep/db/engine.py                                                                                                         |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/db/seed.py                                                                                                           |       45 |        0 |       16 |        0 |    100% |           |
| app/sep/deps.py                                                                                                              |      252 |        2 |       48 |        1 |     99% |247, 679-\>684, 700 |
| app/sep/inventory.py                                                                                                         |      100 |        5 |       12 |        2 |     94% |84, 95, 264-\>266, 284, 321, 379 |
| app/sep/main.py                                                                                                              |      121 |       15 |       12 |        2 |     87% |162-164, 310-329, 349-\>358, 483-487 |
| app/sep/migrations/\_discovery.py                                                                                            |       41 |        2 |       20 |        3 |     92% |65, 97, 133-\>130 |
| app/sep/migrations/\_orphan\_heads.py                                                                                        |       37 |        0 |        8 |        0 |    100% |           |
| app/sep/migrations/env.py                                                                                                    |       41 |        5 |        4 |        2 |     84% |40-\>43, 69-80, 123 |
| app/sep/migrations/versions/2024\_10\_07\_1450-7f4dec8bc76a\_create\_sync\_tables.py                                         |       26 |        8 |        0 |        0 |     69% |     69-76 |
| app/sep/migrations/versions/2024\_10\_08\_2047-eeac2926bbea\_remove\_task\_history\_id\_field.py                             |       12 |        1 |        0 |        0 |     92% |        45 |
| app/sep/migrations/versions/2025\_08\_08\_1005-9307f0f5ee54\_create\_snippet\_table.py                                       |       16 |        3 |        0 |        0 |     81% |     59-61 |
| app/sep/migrations/versions/2026\_03\_02\_1612-810c31754b54\_add\_index\_for\_syncinstance\_syncer.py                        |       12 |        1 |        0 |        0 |     92% |        45 |
| app/sep/migrations/versions/2026\_05\_18\_2014-ed97b99eef38\_add\_setting\_override\_table.py                                |       28 |        9 |        4 |        1 |     62% | 44, 87-96 |
| app/sep/migrations/versions/2026\_06\_01\_1530-e5c224619161\_add\_appstate\_table.py                                         |       14 |        2 |        0 |        0 |     86% |     53-54 |
| app/sep/migrations/versions/2026\_06\_02\_1512-378c0872642f\_extend\_setting\_class\_enum\_settings\_alert.py                |       25 |        9 |        6 |        2 |     58% |51, 55, 85-99 |
| app/sep/migrations/versions/2026\_06\_15\_1725-64f10ead74f6\_add\_seppluginperiodictask.py                                   |       16 |        3 |        0 |        0 |     81% |     55-57 |
| app/sep/migrations/versions/2026\_06\_16\_1200-a7c4e9f1b2d3\_add\_lifecycle\_state\_to\_app\_state.py                        |       26 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_16\_1600-b8d5f2a9c1e4\_add\_apprunningtask\_table.py                                   |       16 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_22\_1223-410eedfc5b43\_merge\_heads.py                                                 |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_22\_1400-c97e7e47c935\_extend\_setting\_class\_enum\_anonymizer.py                     |       25 |        9 |        6 |        2 |     58% |51, 55, 88-101 |
| app/sep/migrations/versions/2026\_06\_30\_1200-a1f4c7e9b2d3\_extend\_setting\_class\_enum\_alerts.py                         |       25 |        9 |        6 |        2 |     58% |51, 55, 90-103 |
| app/sep/migrations/versions/2026\_07\_02\_1000-f1a2b3c4d5e6\_merge\_heads\_before\_inventory\_settings.py                    |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_07\_02\_1001-a2b3c4d5e6f7\_extend\_setting\_class\_enum\_inventory.py                      |       27 |        3 |        6 |        3 |     82% |63, 67, 94 |
| app/sep/migrations/versions/2026\_08\_08\_0306-cf94cc04be4b\_drop\_session\_and\_messages\_setting\_.py                      |       30 |        3 |        6 |        3 |     83% |73, 106, 110 |
| app/sep/migrations/versions/2026\_08\_12\_1200-d1e2f3a4b5c6\_extend\_setting\_class\_enum\_health\_report.py                 |       27 |        3 |        6 |        3 |     82% |63, 67, 94 |
| app/sep/migrations/versions/2026\_08\_17\_2210-74720aeda25b\_drop\_setting\_class\_check\_constraint.py                      |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_08\_25\_1902-867df844fe17\_add\_sync\_run\_state\_and\_entity\_absence\_.py                |       32 |        0 |        0 |        0 |    100% |           |
| app/sep/models.py                                                                                                            |       75 |        1 |        2 |        1 |     97% |       254 |
| app/sep/periodic\_tasks.py                                                                                                   |       55 |        0 |       20 |        0 |    100% |           |
| app/sep/routes/artifacts.py                                                                                                  |       38 |        1 |       14 |        1 |     96% |        87 |
| app/sep/routes/download\_files.py                                                                                            |       44 |        0 |        8 |        1 |     98% |   88-\>94 |
| app/sep/routes/execution\_events.py                                                                                          |       12 |        0 |        2 |        0 |    100% |           |
| app/sep/routes/stream\_logs.py                                                                                               |       78 |       26 |       12 |        4 |     64% |88-100, 109, 113-129, 131-136, 188-\>183, 196-201, 203-207, 212-217 |
| app/sep/settings\_override.py                                                                                                |       43 |        0 |        2 |        0 |    100% |           |
| app/sep/snippets/builtin\_manifest.py                                                                                        |       26 |        0 |        6 |        0 |    100% |           |
| app/sep/snippets/celery.py                                                                                                   |       99 |        5 |       40 |        5 |     93% |85, 93-94, 203-\>210, 239, 265 |
| app/sep/snippets/checksums.py                                                                                                |       16 |        0 |        2 |        0 |    100% |           |
| app/sep/snippets/config.py                                                                                                   |      131 |       17 |       20 |        7 |     83% |126, 200-206, 219, 269, 351-356, 436-\>455, 443, 454, 470-473 |
| app/sep/snippets/constants.py                                                                                                |        1 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/crud.py                                                                                                     |       54 |        0 |       12 |        1 |     98% | 177-\>179 |
| app/sep/snippets/deps.py                                                                                                     |       87 |        8 |       26 |        2 |     88% |59, 130-132, 229, 261-268 |
| app/sep/snippets/list\_query.py                                                                                              |       15 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/masking.py                                                                                                  |      158 |        5 |       76 |        5 |     96% |156, 190, 192, 229-230, 321-\>316 |
| app/sep/snippets/models/constants.py                                                                                         |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/models/meta.py                                                                                              |      217 |        1 |       74 |        3 |     99% |549, 697-\>699, 699-\>701 |
| app/sep/snippets/models/responses.py                                                                                         |       28 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/models/snippet.py                                                                                           |      338 |        5 |       78 |        3 |     98% |237-\>260, 261-262, 665-667 |
| app/sep/snippets/schema.py                                                                                                   |       97 |        4 |       34 |        1 |     96% |157-159, 370 |
| app/sep/snippets/script\_source.py                                                                                           |       96 |        1 |       22 |        1 |     98% |       355 |
| app/sep/snippets/utils.py                                                                                                    |       32 |        0 |       10 |        0 |    100% |           |
| app/sep/sync/constants.py                                                                                                    |        3 |        0 |        0 |        0 |    100% |           |
| app/sep/sync/exceptions.py                                                                                                   |       25 |        0 |        0 |        0 |    100% |           |
| app/sep/sync/health.py                                                                                                       |       53 |        0 |        8 |        0 |    100% |           |
| app/sep/sync/models.py                                                                                                       |      403 |       40 |      104 |       19 |     86% |117, 119-126, 140, 161, 167-\>169, 170-\>172, 257-\>267, 354-356, 385-\>383, 474-475, 863-\>exit, 881, 895, 915-916, 1002, 1038-1039, 1075-\>exit, 1126, 1139, 1163-1165, 1198-\>exit, 1243, 1256, 1313-\>exit, 1358, 1502-1504, 1612-1614, 1619-1625, 1629 |
| app/sep/sync/syncers/mysql/payload.py                                                                                        |      175 |       47 |       54 |        5 |     69% |156-\>164, 240-244, 249-254, 267-273, 277-300, 354-\>370, 373, 394-402, 421 |
| app/sep/sync/syncers/mysql/syncer.py                                                                                         |      241 |        2 |       94 |        5 |     98% |111, 604-\>605, 716, 819-\>823, 821-\>820 |
| app/sep/sync/syncers/pmm.py                                                                                                  |      133 |        1 |       34 |        3 |     98% |144, 430-\>437, 480-\>485 |
| app/sep/sync/syncers/system\_facts/payload.py                                                                                |      235 |       19 |       78 |       12 |     90% |52-\>58, 147-148, 176, 222-224, 231, 233-\>229, 244-251, 261-\>263, 263-\>265, 265-\>267, 282-284, 290-292, 316, 415-\>417, 417-\>419, 522, 533 |
| app/sep/sync/syncers/system\_facts/syncer.py                                                                                 |      119 |        6 |       28 |        3 |     94% |175-176, 251, 262-\>260, 316-317, 356 |
| app/sep/tasks.py                                                                                                             |       31 |        0 |       12 |        2 |     95% |69-\>84, 73-\>76 |
| app/sep/utils/forms.py                                                                                                       |       20 |        0 |        6 |        0 |    100% |           |
| app/sep/utils/jinja.py                                                                                                       |       61 |       10 |       10 |        1 |     79% |105, 124, 135-140, 171-172 |
| app/tasks/alert\_hooks.py                                                                                                    |       23 |        0 |        2 |        0 |    100% |           |
| app/tasks/anonymizer/anonymize.py                                                                                            |       56 |        0 |       18 |        3 |     96% |75-\>82, 97-\>104, 118-\>122 |
| app/tasks/anonymizer/config.py                                                                                               |       30 |        1 |        6 |        1 |     94% |        81 |
| app/tasks/anonymizer/entities.py                                                                                             |       28 |        0 |        2 |        0 |    100% |           |
| app/tasks/celery.py                                                                                                          |      353 |       19 |       80 |        7 |     92% |261-\>275, 270-\>272, 469, 542-546, 719-\>755, 721-738, 889, 958, 981-982, 1085-\>1100 |
| app/tasks/config.py                                                                                                          |       48 |        0 |        4 |        0 |    100% |           |
| app/tasks/connectivity/constants.py                                                                                          |        5 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/models.py                                                                                             |       11 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/payload.py                                                                                            |       69 |        1 |        8 |        1 |     97% |       164 |
| app/tasks/connectivity/routes.py                                                                                             |       16 |        0 |        2 |        0 |    100% |           |
| app/tasks/connectivity/service.py                                                                                            |      146 |        2 |       54 |        6 |     96% |173, 432-\>431, 452-\>451, 458-\>457, 473, 485-\>484 |
| app/tasks/crud.py                                                                                                            |      282 |        4 |       70 |        5 |     97% |538-\>540, 541, 543, 668, 858 |
| app/tasks/db/engine.py                                                                                                       |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/db/seed.py                                                                                                         |      144 |        9 |       38 |        7 |     90% |824-\>837, 838-\>852, 1017-1025, 1030-\>1010, 1036-1038, 1049, 1061, 1094 |
| app/tasks/deps.py                                                                                                            |      110 |        3 |       30 |        0 |     98% |     64-66 |
| app/tasks/execution/exceptions.py                                                                                            |        8 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/celery/models.py                                                                               |       80 |        0 |       14 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/constants.py                                                                             |        1 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/exceptions.py                                                                            |        4 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/models.py                                                                                |      848 |       67 |      290 |       17 |     92% |183, 362, 432-435, 436-\>exit, 455, 498, 732, 794-\>796, 1011-\>1016, 1020, 1026, 1061-1066, 1157-\>1153, 1304-\>1319, 1537, 1628, 2012-2014, 2040-2041, 2078-2079, 2113-2114, 2160-\>2205, 2195-\>2160, 2429-2430, 2471, 2569-2570, 2644-2645, 2668-2724 |
| app/tasks/execution/executors/nomad/steps.py                                                                                 |       20 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/models.py                                                                                                |       70 |        2 |       14 |        0 |     98% |  209, 264 |
| app/tasks/execution/nomad\_lifecycle.py                                                                                      |       54 |        0 |       12 |        2 |     97% |145-\>148, 187-\>exit |
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
| app/tasks/migrations/versions/2026\_06\_02\_1512-6d4cfd37bd3a\_extend\_setting\_class\_enum\_settings\_alert.py              |       25 |        9 |        6 |        2 |     58% |51, 55, 85-99 |
| app/tasks/migrations/versions/2026\_06\_22\_1223-2f5a00236369\_merge\_heads.py                                               |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_06\_22\_1400-abc65df0318a\_extend\_setting\_class\_enum\_anonymizer.py                   |       25 |        9 |        6 |        2 |     58% |51, 55, 88-101 |
| app/tasks/migrations/versions/2026\_06\_22\_1830-c4e8f0a3b1d2\_add\_alert\_detail\_builder\_to\_task.py                      |       14 |        1 |        0 |        0 |     93% |        60 |
| app/tasks/migrations/versions/2026\_06\_30\_1200-b2e5d8f0c3a4\_extend\_setting\_class\_enum\_alerts.py                       |       25 |        9 |        6 |        2 |     58% |51, 55, 90-103 |
| app/tasks/migrations/versions/2026\_06\_30\_1200-b7e1c0a4d9f2\_add\_taskhistory\_log\_retention\_index.py                    |       25 |        9 |        8 |        2 |     55% |65-66, 70-\>exit, 78-85 |
| app/tasks/migrations/versions/2026\_06\_30\_1838-fa5b80a1c8e0\_merge\_tasks\_migration\_heads.py                             |        9 |        1 |        0 |        0 |     89% |        38 |
| app/tasks/migrations/versions/2026\_06\_30\_1839-e3d856712405\_add\_taskhistory\_log\_stream\_end\_offset\_.py               |       23 |        8 |        4 |        1 |     59% |57-58, 67-74 |
| app/tasks/migrations/versions/2026\_06\_30\_1840-b74f05a17c8d\_rewrite\_persisted\_plugins\_module\_paths\_.py               |       36 |       19 |       16 |        1 |     35% |71-91, 101 |
| app/tasks/migrations/versions/2026\_07\_01\_1142-60bf743eb469\_add\_taskhistory\_log\_state\_nomad\_cursor\_.py              |       14 |        2 |        0 |        0 |     86% |     61-62 |
| app/tasks/migrations/versions/2026\_07\_01\_1142-f028a195fbda\_merge\_tasks\_migration\_heads.py                             |        9 |        1 |        0 |        0 |     89% |        38 |
| app/tasks/migrations/versions/2026\_07\_01\_1848-8657d05d27da\_merge\_tasks\_migration\_heads.py                             |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_07\_02\_1001-b3c4d5e6f7a8\_extend\_setting\_class\_enum\_inventory.py                    |       27 |        9 |        6 |        2 |     61% |63, 67, 89-99 |
| app/tasks/migrations/versions/2026\_07\_03\_1200-a1f4c9e2b7d8\_add\_taskhistory\_log\_allocation\_epoch.py                   |       11 |        1 |        0 |        0 |     91% |        57 |
| app/tasks/migrations/versions/2026\_07\_06\_1303-d25887ee3fea\_merge\_tasks\_migration\_heads.py                             |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_07\_06\_1900-13e897d11734\_relativize\_task\_payload\_refs.py                            |       48 |        2 |       16 |        2 |     94% |   74, 105 |
| app/tasks/migrations/versions/2026\_07\_25\_0217-27a11549ef43\_add\_run\_result\_recorder\_to\_task.py                       |       12 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_07\_30\_1300-c8e4a2b91f70\_rename\_log\_cursor\_columns\_executor\_neutral.py            |       24 |        1 |        4 |        1 |     93% |        64 |
| app/tasks/migrations/versions/2026\_08\_08\_0306-6a19d56d7985\_drop\_messages\_setting\_overrides.py                         |       27 |        9 |        6 |        1 |     58% | 61, 90-99 |
| app/tasks/migrations/versions/2026\_08\_12\_1200-e2f3a4b5c6d7\_extend\_setting\_class\_enum\_health\_report.py               |       27 |        9 |        6 |        2 |     61% |63, 67, 89-99 |
| app/tasks/migrations/versions/2026\_08\_13\_2143-a19da5cf0bca\_add\_taskhistory\_log\_state\_capture\_status.py              |       20 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_08\_17\_2210-7d2e869ac188\_drop\_setting\_class\_check\_constraint.py                    |        9 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_09\_01\_1329-3a4dfc2a2be8\_add\_unlaunchable\_to\_taskhistory\_status\_enum.py           |       18 |        0 |        0 |        0 |    100% |           |
| app/tasks/models.py                                                                                                          |      357 |        4 |       70 |        5 |     98% |207, 650-\>653, 657, 674-\>687, 1205-\>1207, 1217-\>1219, 1242-1243 |
| app/tasks/periodic/crud.py                                                                                                   |       31 |        0 |        0 |        0 |    100% |           |
| app/tasks/periodic/deps.py                                                                                                   |       11 |        0 |        0 |        0 |    100% |           |
| app/tasks/periodic/models.py                                                                                                 |      111 |        6 |       34 |        6 |     92% |224, 259, 313, 329, 346, 393 |
| app/tasks/periodic/routes.py                                                                                                 |       64 |        4 |       12 |        2 |     92% |91, 138-\>140, 160-163, 176 |
| app/tasks/periodic/utils.py                                                                                                  |       22 |        0 |        6 |        1 |     96% |   85-\>86 |
| app/tasks/routes.py                                                                                                          |      238 |       21 |       46 |        4 |     90% |153-157, 240-246, 279, 329-338, 345, 435, 478, 493, 653, 667, 675, 701, 709-\>711, 732-733 |
| app/tasks/run\_result.py                                                                                                     |       59 |        0 |       14 |        0 |    100% |           |
| app/tasks/settings/routes.py                                                                                                 |       13 |        0 |        0 |        0 |    100% |           |
| **TOTAL**                                                                                                                    | **28416** | **1727** | **6970** |  **648** | **92%** |           |


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