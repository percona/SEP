# Repository Coverage

[Full report](https://htmlpreview.github.io/?https://github.com/percona/SEP/blob/python-coverage-comment-action-data/htmlcov/index.html)

| Name                                                                                                                         |    Stmts |     Miss |   Branch |   BrPart |   Cover |   Missing |
|----------------------------------------------------------------------------------------------------------------------------- | -------: | -------: | -------: | -------: | ------: | --------: |
| app/api/deps.py                                                                                                              |       96 |        0 |       24 |        0 |    100% |           |
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
| app/core/auth/models.py                                                                                                      |       97 |        0 |        2 |        0 |    100% |           |
| app/core/auth/providers/casdoor/models.py                                                                                    |       95 |        6 |       18 |        1 |     90% |229-235, 265 |
| app/core/auth/providers/casdoor/provider.py                                                                                  |       14 |        0 |        0 |        0 |    100% |           |
| app/core/auth/providers/casdoor/sdk.py                                                                                       |      123 |       49 |       26 |        3 |     56% |51, 106-107, 145-\>147, 161-170, 190-191, 210-217, 243-265, 273, 292-300, 316-319, 355-\>354, 373-378, 386-387, 416-422, 432-438 |
| app/core/auth/providers/grafana/models.py                                                                                    |      228 |        4 |       44 |        2 |     98% |459, 804, 825-826 |
| app/core/auth/providers/grafana/provider.py                                                                                  |       25 |        0 |        4 |        0 |    100% |           |
| app/core/auth/providers/grafana/sdk.py                                                                                       |      141 |        0 |       22 |        0 |    100% |           |
| app/core/auth/utils.py                                                                                                       |        6 |        1 |        0 |        0 |     83% |        35 |
| app/core/celery/bootstrap.py                                                                                                 |       31 |        2 |        2 |        1 |     91% |  141, 145 |
| app/core/celery/config.py                                                                                                    |       35 |        0 |        2 |        0 |    100% |           |
| app/core/celery/crud.py                                                                                                      |       26 |        1 |        4 |        0 |     97% |        97 |
| app/core/celery/db.py                                                                                                        |        8 |        0 |        0 |        0 |    100% |           |
| app/core/celery/deps.py                                                                                                      |       10 |        0 |        0 |        0 |    100% |           |
| app/core/celery/migrations.py                                                                                                |        6 |        0 |        0 |        0 |    100% |           |
| app/core/celery/models.py                                                                                                    |       68 |        1 |        8 |        1 |     97% |       107 |
| app/core/celery/schedules.py                                                                                                 |       44 |        1 |       16 |        1 |     97% |       178 |
| app/core/celery/utils.py                                                                                                     |       35 |        0 |       12 |        0 |    100% |           |
| app/core/config.py                                                                                                           |      277 |        7 |       54 |        6 |     96% |259-\>exit, 336, 621, 799, 879, 955, 968, 1006-\>1008, 1011 |
| app/core/db/config.py                                                                                                        |       46 |        0 |       10 |        0 |    100% |           |
| app/core/db/crud.py                                                                                                          |      287 |        7 |       74 |        7 |     96% |250, 343-\>345, 345-\>347, 347-\>349, 356-\>372, 442, 589-592, 1013, 1017, 1263 |
| app/core/db/deps.py                                                                                                          |        8 |        0 |        0 |        0 |    100% |           |
| app/core/db/exception\_handlers.py                                                                                           |       37 |        1 |       10 |        1 |     96% |        82 |
| app/core/db/in\_memory\_list\_query.py                                                                                       |       73 |        0 |       14 |        0 |    100% |           |
| app/core/db/list\_query.py                                                                                                   |       87 |        0 |       24 |        0 |    100% |           |
| app/core/db/models.py                                                                                                        |       14 |        0 |        0 |        0 |    100% |           |
| app/core/db/sql\_types.py                                                                                                    |       37 |        0 |       12 |        0 |    100% |           |
| app/core/db/utils.py                                                                                                         |      172 |       10 |       56 |        5 |     92% |206, 305-316, 334, 355, 424, 453 |
| app/core/encryption.py                                                                                                       |       43 |        0 |        2 |        0 |    100% |           |
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
| app/core/requests/remote\_api.py                                                                                             |      345 |        1 |       74 |        2 |     99% |363, 943-\>942 |
| app/core/security.py                                                                                                         |       18 |        0 |        4 |        0 |    100% |           |
| app/core/settings\_override/alembic\_ops.py                                                                                  |      112 |       11 |       36 |       12 |     84% |89, 92, 94, 96-\>98, 116, 118, 154, 156, 170, 172, 213, 257 |
| app/core/settings\_override/api/export.py                                                                                    |        9 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/api/models.py                                                                                    |       24 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/api/routes.py                                                                                    |      320 |       39 |      100 |        8 |     86% |331, 470, 494, 624-631, 758, 787-797, 831-837, 845, 979, 1009, 1163, 1395-\>1432, 1405-1416, 1420-1431, 1433, 1487, 1489-1490, 1544, 1546, 1548 |
| app/core/settings\_override/cache.py                                                                                         |      127 |       13 |       46 |        6 |     87% |200-205, 218-223, 309, 372, 413, 417-424 |
| app/core/settings\_override/constants.py                                                                                     |        5 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/lifecycle.py                                                                                     |      123 |        1 |       34 |        1 |     99% |70-\>exit, 536 |
| app/core/settings\_override/manager.py                                                                                       |        5 |        0 |        0 |        0 |    100% |           |
| app/core/settings\_override/models.py                                                                                        |       48 |        2 |        8 |        2 |     93% |  121, 123 |
| app/core/settings\_override/policy.py                                                                                        |       29 |        0 |        6 |        0 |    100% |           |
| app/core/settings\_override/proxy.py                                                                                         |       21 |        0 |        2 |        0 |    100% |           |
| app/core/settings\_override/registry.py                                                                                      |      296 |        1 |      116 |        1 |     99% |      1201 |
| app/core/settings\_override/resolution.py                                                                                    |      116 |        0 |       62 |        0 |    100% |           |
| app/core/settings\_override/secret\_preservation.py                                                                          |      267 |        0 |      154 |        0 |    100% |           |
| app/core/settings\_override/secret\_storage.py                                                                               |      154 |        4 |       50 |        5 |     96% |575, 577-\>579, 603, 754, 784 |
| app/core/settings\_override/worker.py                                                                                        |       59 |        1 |       14 |        1 |     97% |       214 |
| app/core/utils/async\_run.py                                                                                                 |       13 |        0 |        0 |        0 |    100% |           |
| app/core/utils/cache.py                                                                                                      |       93 |        4 |       16 |        1 |     94% |56-58, 204 |
| app/core/utils/cli\_args.py                                                                                                  |       12 |        0 |        0 |        0 |    100% |           |
| app/core/utils/date\_time.py                                                                                                 |        8 |        0 |        2 |        0 |    100% |           |
| app/core/utils/dict.py                                                                                                       |       29 |        4 |       12 |        0 |     85% |   165-168 |
| app/core/utils/fields.py                                                                                                     |      259 |        7 |       36 |        5 |     96% |175, 247-248, 394, 398, 647, 779 |
| app/core/utils/imports.py                                                                                                    |       28 |        0 |        8 |        0 |    100% |           |
| app/core/utils/iterators.py                                                                                                  |       18 |        0 |        6 |        0 |    100% |           |
| app/core/utils/json\_pointer.py                                                                                              |       41 |        0 |       22 |        0 |    100% |           |
| app/core/utils/lazy.py                                                                                                       |       31 |        0 |        4 |        0 |    100% |           |
| app/core/utils/openapi.py                                                                                                    |      246 |        5 |      120 |        7 |     96% |141, 513, 515-\>514, 520-521, 564-\>566, 583-\>582, 600 |
| app/core/utils/path.py                                                                                                       |       40 |        0 |       14 |        0 |    100% |           |
| app/core/utils/pydantic.py                                                                                                   |       74 |        0 |       22 |        0 |    100% |           |
| app/core/utils/serialization.py                                                                                              |        7 |        0 |        0 |        0 |    100% |           |
| app/core/utils/strings.py                                                                                                    |       29 |        1 |        6 |        1 |     94% |        67 |
| app/inventory/config.py                                                                                                      |       12 |        0 |        0 |        0 |    100% |           |
| app/inventory/constants.py                                                                                                   |       15 |        0 |        0 |        0 |    100% |           |
| app/inventory/crud.py                                                                                                        |      386 |        6 |       72 |        3 |     98% |338, 506-508, 782-\>784, 969, 1297, 1821-\>exit |
| app/inventory/db.py                                                                                                          |        6 |        0 |        0 |        0 |    100% |           |
| app/inventory/deps.py                                                                                                        |       63 |        9 |        4 |        0 |     81% |63-65, 272-274, 293-295 |
| app/inventory/main.py                                                                                                        |       44 |        6 |        2 |        1 |     85% |52, 97-98, 136-140 |
| app/inventory/migrations/env.py                                                                                              |       36 |        5 |        4 |        2 |     82% |37-\>44, 65-77, 120 |
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
| app/inventory/migrations/versions/2026\_09\_04\_1842-74b2ad210981\_encrypt\_secret\_setting\_overrides.py                    |       17 |        0 |        0 |        0 |    100% |           |
| app/inventory/migrations/versions/2026\_09\_04\_1853-f7f329837258\_add\_settingoverride\_updated\_by.py                      |        9 |        0 |        0 |        0 |    100% |           |
| app/inventory/migrations/versions/2026\_09\_14\_2243-168ac77b6775\_encrypt\_credential\_url\_setting\_overrides.py           |       17 |        0 |        0 |        0 |    100% |           |
| app/inventory/migrations/versions/2026\_09\_16\_0212-b351dd0aaed8\_add\_can\_elevate\_to\_host\_system\_.py                  |       10 |        0 |        0 |        0 |    100% |           |
| app/inventory/migrations/versions/2026\_09\_18\_1512-6ee7bfe9c9d3\_unmark\_secret\_setting\_overrides.py                     |       16 |        0 |        0 |        0 |    100% |           |
| app/inventory/models.py                                                                                                      |      156 |        0 |        8 |        0 |    100% |           |
| app/inventory/routes/collection.py                                                                                           |       23 |        7 |        6 |        1 |     59% |73-74, 76-80 |
| app/inventory/routes/nodes.py                                                                                                |       78 |        2 |        4 |        0 |     95% |  328, 330 |
| app/inventory/routes/schemas.py                                                                                              |       42 |        0 |        0 |        0 |    100% |           |
| app/inventory/routes/services.py                                                                                             |       74 |        3 |        6 |        0 |     91% |247, 249, 285 |
| app/inventory/routes/tables.py                                                                                               |       34 |        0 |        0 |        0 |    100% |           |
| app/inventory/settings/routes.py                                                                                             |       12 |        0 |        0 |        0 |    100% |           |
| app/main.py                                                                                                                  |       91 |       23 |        6 |        1 |     73% |   261-315 |
| app/sep/api/constants.py                                                                                                     |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/api/deps.py                                                                                                          |       26 |        0 |        8 |        0 |    100% |           |
| app/sep/api/host\_resolution.py                                                                                              |        9 |        0 |        4 |        0 |    100% |           |
| app/sep/api/models.py                                                                                                        |       14 |        0 |        0 |        0 |    100% |           |
| app/sep/api/openapi.py                                                                                                       |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/api/proxy.py                                                                                                         |       16 |        0 |        2 |        0 |    100% |           |
| app/sep/api/router.py                                                                                                        |       41 |        0 |        4 |        0 |    100% |           |
| app/sep/api/routes/app\_info.py                                                                                              |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/app\_state.py                                                                                             |       44 |       12 |       10 |        2 |     59% |180, 186, 188-195, 202, 208-209, 237-238, 243-244, 251 |
| app/sep/api/routes/apps.py                                                                                                   |       22 |        3 |        2 |        1 |     83% |87, 107-108 |
| app/sep/api/routes/connectivity\_check.py                                                                                    |       75 |        0 |       24 |        0 |    100% |           |
| app/sep/api/routes/dashboard.py                                                                                              |       35 |        0 |        6 |        0 |    100% |           |
| app/sep/api/routes/delivery\_connection.py                                                                                   |       36 |        0 |        4 |        0 |    100% |           |
| app/sep/api/routes/hosts.py                                                                                                  |       47 |        0 |       10 |        0 |    100% |           |
| app/sep/api/routes/periodic\_tasks.py                                                                                        |       35 |        0 |        2 |        0 |    100% |           |
| app/sep/api/routes/schemas.py                                                                                                |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/api/routes/services.py                                                                                               |       17 |        0 |        2 |        0 |    100% |           |
| app/sep/api/routes/settings.py                                                                                               |      129 |        6 |       50 |        3 |     94% |138, 143, 298-300, 328 |
| app/sep/api/routes/task\_history.py                                                                                          |       30 |        0 |        4 |        0 |    100% |           |
| app/sep/api/routes/task\_stats.py                                                                                            |       15 |        0 |        0 |        0 |    100% |           |
| app/sep/api/task\_history\_actors.py                                                                                         |       54 |        0 |       22 |        0 |    100% |           |
| app/sep/api/task\_history\_merge.py                                                                                          |       70 |        3 |       24 |        1 |     96% | 61, 65-66 |
| app/sep/app\_drain.py                                                                                                        |       83 |        2 |       14 |        2 |     96% |137-\>139, 208, 216 |
| app/sep/apps/alert\_troubleshooting/api\_routes.py                                                                           |       23 |        4 |        2 |        0 |     76% |64-65, 73-80 |
| app/sep/apps/alert\_troubleshooting/app.py                                                                                   |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alert\_troubleshooting/deps.py                                                                                  |      109 |        4 |       44 |        3 |     95% |108, 110-\>112, 223, 236, 320 |
| app/sep/apps/alert\_troubleshooting/models.py                                                                                |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alert\_troubleshooting/schema.py                                                                                |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/api\_routes.py                                                                                           |      129 |       16 |       18 |        0 |     86% |178, 194-197, 242-252 |
| app/sep/apps/alerts/app.py                                                                                                   |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/app\_owned\_settings.py                                                                                  |        3 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/celery.py                                                                                                |       46 |        1 |       10 |        0 |     98% |        39 |
| app/sep/apps/alerts/config.py                                                                                                |       13 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/crud.py                                                                                                  |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/deps.py                                                                                                  |       75 |        0 |       16 |        0 |    100% |           |
| app/sep/apps/alerts/loader.py                                                                                                |       22 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/alerts/migrations/versions/2026\_04\_20\_1817-d21ad387df7a\_create\_alert\_backup\_table.py                     |       14 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/alerts/models.py                                                                                                |       45 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alerts/restore.py                                                                                               |       95 |        0 |       26 |        0 |    100% |           |
| app/sep/apps/alters/api\_routes.py                                                                                           |       38 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alters/app.py                                                                                                   |       10 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/alters/deps.py                                                                                                  |      211 |       11 |       62 |       11 |     92% |101, 131-\>143, 137-\>136, 141-\>136, 144, 347, 417-418, 557, 580-581, 701, 712, 714, 754-\>758 |
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
| app/sep/apps/atw/api\_routes.py                                                                                              |      272 |       49 |       48 |        2 |     80% |320, 438-439, 541-542, 546-552, 621, 625-654, 656-672, 681, 683-699, 719-721, 931-\>938, 932, 988-992, 994, 996-999, 1017, 1074 |
| app/sep/apps/atw/app.py                                                                                                      |       15 |        0 |        4 |        0 |    100% |           |
| app/sep/apps/atw/batch.py                                                                                                    |       76 |        0 |        8 |        0 |    100% |           |
| app/sep/apps/atw/categories.py                                                                                               |       34 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/atw/celery.py                                                                                                   |       23 |        6 |        2 |        0 |     68% |43, 55-58, 71 |
| app/sep/apps/atw/config.py                                                                                                   |       19 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/crud.py                                                                                                     |       37 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/atw/deps.py                                                                                                     |       37 |        0 |        8 |        0 |    100% |           |
| app/sep/apps/atw/migrations/versions/2026\_07\_20\_1238-b82887dfe93d\_create\_atw\_incident\_tables.py                       |       24 |        7 |        8 |        2 |     59% |40-\>55, 55-\>exit, 85-94 |
| app/sep/apps/atw/migrations/versions/2026\_07\_24\_1100-c93998e0fa14\_create\_atw\_send\_log\_table.py                       |       20 |        5 |        4 |        1 |     67% |40-\>exit, 81-87 |
| app/sep/apps/atw/migrations/versions/2026\_07\_30\_1200-447ee0172734\_add\_atw\_incident\_closed\_at.py                      |       25 |        2 |        8 |        4 |     82% |41, 43-\>exit, 55, 57-\>exit |
| app/sep/apps/atw/migrations/versions/2026\_09\_16\_0143-488c8bfe0382\_add\_atw\_execution\_outcome\_columns.py               |       43 |       15 |       16 |        3 |     56% |101, 104-\>116, 117-\>exit, 122-138 |
| app/sep/apps/atw/models.py                                                                                                   |       70 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/atw/proxy\_tasks.py                                                                                             |       81 |        1 |       18 |        1 |     98% |       166 |
| app/sep/apps/atw/reconcile.py                                                                                                |       53 |        0 |        8 |        0 |    100% |           |
| app/sep/apps/atw/recorder.py                                                                                                 |       14 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/atw/schema.py                                                                                                   |       13 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/atw/send.py                                                                                                     |      280 |        5 |       52 |        0 |     98% |113, 169, 181, 889-890 |
| app/sep/apps/backup\_mongo/api\_routes.py                                                                                    |       30 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/app.py                                                                                            |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/deps.py                                                                                           |      118 |       14 |       18 |        0 |     84% |   247-266 |
| app/sep/apps/backup\_mongo/models.py                                                                                         |      240 |        0 |       42 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/pbm\_creds\_common.py                                                                             |      159 |        3 |       32 |        1 |     98% |83-\>92, 147-149 |
| app/sep/apps/backup\_mongo/restore/api\_routes.py                                                                            |       34 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/app.py                                                                                    |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/deps.py                                                                                   |      141 |        2 |       18 |        1 |     98% |  183, 462 |
| app/sep/apps/backup\_mongo/restore/models.py                                                                                 |      159 |        7 |       22 |        5 |     93% |79-81, 83, 86-90, 302-\>306, 340-\>342, 640 |
| app/sep/apps/backup\_mongo/restore/schema.py                                                                                 |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/restore/spec.py                                                                                   |       31 |        2 |        0 |        0 |     94% |   190-191 |
| app/sep/apps/backup\_mongo/restore/views.py                                                                                  |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/schema.py                                                                                         |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_mongo/spec.py                                                                                           |       51 |        3 |       24 |        4 |     91% |78, 87-\>90, 131, 136 |
| app/sep/apps/backup\_mongo/views.py                                                                                          |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/app.py                                                                                               |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/deps.py                                                                                              |       60 |        6 |       10 |        1 |     90% |62-63, 66, 103-105 |
| app/sep/apps/backup\_pg/form\_backfill.py                                                                                    |       46 |        4 |       16 |        4 |     87% |44-\>57, 47-48, 49-\>57, 51-\>57, 53-\>57, 85-86 |
| app/sep/apps/backup\_pg/models.py                                                                                            |       49 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/spec.py                                                                                              |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/backup\_pg/views.py                                                                                             |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/checksums/app.py                                                                                                |        7 |        0 |        0 |        0 |    100% |           |
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
| app/sep/apps/dipper/schema.py                                                                                                |       36 |        1 |       10 |        1 |     96% |       240 |
| app/sep/apps/field\_names.py                                                                                                 |        6 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/framework/api.py                                                                                                |      334 |       10 |      130 |        8 |     96% |148-\>146, 203-208, 749, 756, 884, 890, 895, 901, 916, 1325 |
| app/sep/apps/framework/apps.py                                                                                               |      362 |        7 |      148 |        7 |     97% |588, 781, 797, 814, 874, 888, 895 |
| app/sep/apps/framework/base.py                                                                                               |       45 |        2 |        6 |        2 |     92% |  166, 173 |
| app/sep/apps/framework/cascade.py                                                                                            |      197 |        0 |       64 |        2 |     99% |133-\>135, 149-\>151 |
| app/sep/apps/framework/conformance.py                                                                                        |      117 |        6 |       56 |        7 |     92% |72, 216, 245-\>247, 356, 369, 373, 421 |
| app/sep/apps/framework/connectivity.py                                                                                       |       25 |        0 |        6 |        0 |    100% |           |
| app/sep/apps/framework/deps.py                                                                                               |       15 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/framework/form\_audit.py                                                                                        |      146 |        1 |       28 |        1 |     99% |       410 |
| app/sep/apps/framework/form\_backfill.py                                                                                     |      192 |       37 |       30 |        4 |     80% |122, 127, 132, 137, 142, 147, 323-329, 355-361, 364-369, 389-395, 398, 482-\>489, 511-547, 602 |
| app/sep/apps/framework/form\_backfill\_guards.py                                                                             |       10 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/framework/form\_backfill\_inventory.py                                                                          |      141 |       10 |       52 |       12 |     89% |71, 76-\>exit, 144, 147, 151, 164-\>142, 196, 199-\>212, 216, 249, 267, 280-281, 317-\>323 |
| app/sep/apps/framework/form\_backfill\_registry.py                                                                           |       62 |        0 |       20 |        0 |    100% |           |
| app/sep/apps/framework/form\_dsl/conformance.py                                                                              |       46 |        9 |       18 |        3 |     75% |65, 69, 85-93 |
| app/sep/apps/framework/form\_dsl/derivation.py                                                                               |      375 |       22 |      194 |       23 |     91% |258, 275, 492, 513, 520, 526-\>522, 535, 545-\>551, 548-550, 564-\>566, 569, 571-\>566, 573, 590, 596, 623, 633, 641, 647-648, 650, 691, 697, 883 |
| app/sep/apps/framework/form\_dsl/markers.py                                                                                  |      138 |        1 |       20 |        1 |     99% |       256 |
| app/sep/apps/framework/form\_dsl/model.py                                                                                    |       17 |        1 |        2 |        1 |     89% |        70 |
| app/sep/apps/framework/form\_dsl/pt\_toolkit.py                                                                              |       56 |        0 |       26 |        0 |    100% |           |
| app/sep/apps/framework/inventory\_references.py                                                                              |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/framework/list\_query.py                                                                                        |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/framework/registry.py                                                                                           |      206 |        3 |      108 |        3 |     98% |458, 460, 479 |
| app/sep/apps/framework/responses.py                                                                                          |       96 |        1 |       20 |        1 |     98% |        64 |
| app/sep/apps/framework/rules.py                                                                                              |      538 |        7 |      130 |        5 |     98% |323, 328, 333, 545, 861, 1348, 1368 |
| app/sep/apps/framework/scaffold.py                                                                                           |      438 |       29 |      150 |       20 |     91% |305, 316, 328, 447, 544, 547, 567-\>574, 570, 621-623, 657, 698, 702, 910, 1151-1154, 1180, 1182, 1196-1199, 1225, 1230-1233, 1254, 1294 |
| app/sep/apps/framework/schema.py                                                                                             |      440 |        2 |      126 |        2 |     99% |1379, 1983 |
| app/sep/apps/framework/script\_helpers.py                                                                                    |       45 |        0 |        6 |        0 |    100% |           |
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
| app/sep/apps/inventory/deps.py                                                                                               |       77 |        1 |       12 |        0 |     99% |       290 |
| app/sep/apps/inventory/models.py                                                                                             |       31 |        7 |        8 |        3 |     69% |109, 111, 112-\>114, 130-138 |
| app/sep/apps/inventory/sync.py                                                                                               |       76 |        0 |       24 |        0 |    100% |           |
| app/sep/apps/labels.py                                                                                                       |        1 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/meta\_keys.py                                                                                                   |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/api\_routes.py                                                                                   |       23 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/app.py                                                                                           |       13 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/backup\_source\_choices.py                                                                       |       51 |        0 |       20 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/crud.py                                                                                          |       29 |        0 |        4 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/deps.py                                                                                          |       93 |        0 |       22 |        1 |     99% | 335-\>338 |
| app/sep/apps/mysql\_backups/form\_backfill.py                                                                                |       66 |        6 |       22 |        6 |     86% |129-\>151, 132-133, 134-\>151, 136-\>151, 138-\>151, 145, 175-176, 186 |
| app/sep/apps/mysql\_backups/forms.py                                                                                         |      228 |        3 |       20 |        3 |     98% |371, 1355, 1370 |
| app/sep/apps/mysql\_backups/inventory\_references.py                                                                         |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/migrations/versions/2026\_07\_29\_1200-f0a1b2c3d4e5\_create\_mysql\_backup\_run\_table.py        |       22 |        6 |        4 |        1 |     65% |40-\>exit, 89-98 |
| app/sep/apps/mysql\_backups/migrations/versions/2026\_08\_06\_1200-b7c8d9e0f1a2\_add\_service\_id\_to\_mysql\_backup\_run.py |       30 |        0 |       12 |        2 |     95% |66-\>exit, 74-\>exit |
| app/sep/apps/mysql\_backups/models.py                                                                                        |       84 |        1 |       16 |        1 |     98% |        81 |
| app/sep/apps/mysql\_backups/payload\_variants.py                                                                             |       13 |        0 |        4 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/recorder.py                                                                                      |       43 |        0 |       10 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/restore/app.py                                                                                   |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/restore/deps.py                                                                                  |       97 |       10 |       26 |        4 |     89% |127, 135-136, 176-177, 181, 186, 189-190, 218 |
| app/sep/apps/mysql\_backups/restore/form\_backfill.py                                                                        |       57 |        3 |       18 |        1 |     95% |135-136, 149 |
| app/sep/apps/mysql\_backups/restore/models.py                                                                                |      216 |        2 |       44 |        3 |     98% |357-\>361, 1090, 1118 |
| app/sep/apps/mysql\_backups/restore/spec.py                                                                                  |       35 |        1 |        8 |        1 |     95% |       121 |
| app/sep/apps/mysql\_backups/restore/views.py                                                                                 |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/mysql\_backups/spec.py                                                                                          |       36 |        1 |       12 |        1 |     96% |       155 |
| app/sep/apps/mysql\_backups/views.py                                                                                         |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/nav\_icons.py                                                                                                   |       16 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/om\_inventory/api\_routes.py                                                                                    |      124 |       25 |       28 |        2 |     73% |280, 291-292, 304-306, 324-325, 368, 381-383, 411-412, 429-430, 481-484, 535-\>534, 536, 543-544, 547-548 |
| app/sep/apps/om\_inventory/app.py                                                                                            |       12 |        1 |        2 |        1 |     86% |        59 |
| app/sep/apps/om\_inventory/app\_owned\_settings.py                                                                           |        3 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/om\_inventory/celery.py                                                                                         |       11 |        2 |        0 |        0 |     82% |     51-54 |
| app/sep/apps/om\_inventory/config.py                                                                                         |       26 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/om\_inventory/crud.py                                                                                           |      134 |        4 |       38 |        2 |     97% |328-\>332, 331, 402, 411-417 |
| app/sep/apps/om\_inventory/dispatch.py                                                                                       |      150 |       15 |       42 |        7 |     88% |138, 266-267, 269, 274-\>260, 296, 377-383, 421-422, 450 |
| app/sep/apps/om\_inventory/enumeration.py                                                                                    |       50 |        1 |       16 |        1 |     97% |142-\>146, 155 |
| app/sep/apps/om\_inventory/inventory.py                                                                                      |       22 |       11 |        2 |        0 |     46% |72-82, 98-117 |
| app/sep/apps/om\_inventory/mapping.py                                                                                        |       46 |        1 |       14 |        1 |     97% |       115 |
| app/sep/apps/om\_inventory/migrations/versions/2026\_08\_11\_1200-a3f1c8d24b71\_create\_om\_schema.py                        |       41 |        8 |        8 |        4 |     76% |128, 140-\>169, 169-\>205, 205-\>exit, 298-316 |
| app/sep/apps/om\_inventory/models.py                                                                                         |      109 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/om\_inventory/payload/probe.py                                                                                  |      296 |      130 |      118 |       10 |     55% |96-104, 127-129, 137-147, 257-\>259, 261-\>255, 265, 275-\>268, 277-\>268, 281, 301-325, 342-\>340, 414-419, 451-468, 484-506, 522-546, 585-611, 660-674, 683-687, 873-928, 932 |
| app/sep/apps/om\_inventory/schema.py                                                                                         |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/om\_inventory/service.py                                                                                        |      257 |       20 |       74 |        7 |     92% |92-104, 185, 402, 439, 635, 685-690, 779-780, 905-910, 933-943 |
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
| app/sep/apps/shared/backups/columns.py                                                                                       |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/shared/backups/edit\_form.py                                                                                    |       17 |        0 |       10 |        0 |    100% |           |
| app/sep/apps/shared/backups/responses.py                                                                                     |        3 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/shared/disk\_script\_source.py                                                                                  |       82 |        2 |       18 |        2 |     96% |  216, 263 |
| app/sep/apps/shared/om/config.py                                                                                             |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/snippets/app.py                                                                                                 |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/snippets/extra\_routes.py                                                                                       |       71 |        6 |       10 |        0 |     93% |80-82, 99, 183, 214 |
| app/sep/apps/tasks/api\_routes.py                                                                                            |       30 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/tasks/app.py                                                                                                    |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/tasks/deps.py                                                                                                   |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/tasks/models.py                                                                                                 |       30 |        1 |        2 |        1 |     94% |       112 |
| app/sep/apps/tasks/schema.py                                                                                                 |        2 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/topology/api\_routes.py                                                                                         |      138 |       13 |       44 |       11 |     87% |91, 120-\>118, 139, 147, 202, 223, 229, 236-\>226, 240, 280, 283-285, 286-\>276, 302-303 |
| app/sep/apps/topology/app.py                                                                                                 |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/apps/topology/models.py                                                                                              |      112 |        0 |        2 |        0 |    100% |           |
| app/sep/apps/topology/topology.py                                                                                            |      173 |        7 |       58 |        8 |     94% |118-119, 122-\>114, 153, 156-157, 226-\>228, 229-\>231, 407, 491-\>501, 505 |
| app/sep/artifact\_constants.py                                                                                               |        8 |        0 |        0 |        0 |    100% |           |
| app/sep/bundle\_upload/factory.py                                                                                            |       37 |        1 |       10 |        1 |     96% |        71 |
| app/sep/bundle\_upload/plan.py                                                                                               |      302 |        2 |       90 |        2 |     99% |1071, 1220 |
| app/sep/bundle\_upload/resolver.py                                                                                           |       56 |        0 |       14 |        0 |    100% |           |
| app/sep/bundle\_upload/seam.py                                                                                               |       12 |        0 |        0 |        0 |    100% |           |
| app/sep/clients/pmm.py                                                                                                       |      292 |        2 |       74 |        3 |     99% |565, 567, 980-\>982 |
| app/sep/config.py                                                                                                            |      241 |        4 |       58 |        4 |     97% |181, 230, 439, 747 |
| app/sep/connectivity.py                                                                                                      |       39 |        4 |        2 |        1 |     88% |84, 163-169 |
| app/sep/crud.py                                                                                                              |      157 |        0 |       28 |        0 |    100% |           |
| app/sep/db/engine.py                                                                                                         |        7 |        0 |        0 |        0 |    100% |           |
| app/sep/db/seed.py                                                                                                           |       52 |        0 |       16 |        0 |    100% |           |
| app/sep/deps.py                                                                                                              |      270 |        1 |       50 |        1 |     99% |697-\>702, 718 |
| app/sep/inventory.py                                                                                                         |      100 |        7 |       12 |        1 |     93% |84, 95, 203, 284, 321, 345, 379 |
| app/sep/main.py                                                                                                              |      124 |       15 |       12 |        2 |     88% |163-165, 337-356, 376-\>385, 510-514 |
| app/sep/migrations/\_discovery.py                                                                                            |       41 |        2 |       20 |        3 |     92% |65, 97, 133-\>130 |
| app/sep/migrations/\_orphan\_heads.py                                                                                        |       37 |        0 |        8 |        0 |    100% |           |
| app/sep/migrations/env.py                                                                                                    |       49 |        5 |        6 |        2 |     87% |41-\>44, 84-96, 158 |
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
| app/sep/migrations/versions/2026\_09\_04\_1841-e4b3754984d8\_encrypt\_secret\_setting\_overrides.py                          |       51 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_09\_04\_1852-c9880f0ac1bd\_add\_settingoverride\_updated\_by.py                            |        9 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_09\_14\_2243-a833d33359d7\_encrypt\_credential\_url\_setting\_overrides.py                 |       51 |        0 |        0 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_09\_18\_1512-cbc3026013de\_unmark\_secret\_setting\_overrides.py                           |       52 |        0 |        0 |        0 |    100% |           |
| app/sep/models.py                                                                                                            |       75 |        1 |        2 |        1 |     97% |       254 |
| app/sep/periodic\_tasks.py                                                                                                   |      111 |        0 |       42 |        0 |    100% |           |
| app/sep/routes/artifacts.py                                                                                                  |       38 |        1 |       14 |        1 |     96% |        87 |
| app/sep/routes/download\_files.py                                                                                            |       68 |        0 |       14 |        2 |     98% |109-\>exit, 173-\>179 |
| app/sep/routes/execution\_events.py                                                                                          |       12 |        0 |        2 |        0 |    100% |           |
| app/sep/routes/stream\_logs.py                                                                                               |       78 |       26 |       12 |        4 |     64% |88-100, 109, 113-129, 131-136, 188-\>183, 196-201, 203-207, 212-217 |
| app/sep/settings\_override.py                                                                                                |       46 |        0 |        2 |        0 |    100% |           |
| app/sep/snippets/builtin\_manifest.py                                                                                        |       26 |        0 |        6 |        0 |    100% |           |
| app/sep/snippets/celery.py                                                                                                   |       99 |        5 |       40 |        5 |     93% |85, 93-94, 203-\>210, 239, 265 |
| app/sep/snippets/checksums.py                                                                                                |       16 |        0 |        2 |        0 |    100% |           |
| app/sep/snippets/config.py                                                                                                   |      142 |       17 |       24 |        7 |     84% |150, 224-230, 243, 293, 375-380, 460-\>479, 467, 478, 494-497 |
| app/sep/snippets/constants.py                                                                                                |        1 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/crud.py                                                                                                     |       54 |        0 |       12 |        1 |     98% | 177-\>179 |
| app/sep/snippets/deps.py                                                                                                     |       87 |        8 |       26 |        2 |     88% |59, 130-132, 229, 261-268 |
| app/sep/snippets/list\_query.py                                                                                              |       15 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/masking.py                                                                                                  |      158 |        5 |       76 |        5 |     96% |156, 190, 192, 229-230, 321-\>316 |
| app/sep/snippets/models/constants.py                                                                                         |        5 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/models/meta.py                                                                                              |      233 |        1 |       74 |        3 |     99% |593, 741-\>743, 743-\>745 |
| app/sep/snippets/models/responses.py                                                                                         |       28 |        0 |        0 |        0 |    100% |           |
| app/sep/snippets/models/snippet.py                                                                                           |      338 |        5 |       78 |        3 |     98% |241-\>264, 265-266, 671-673 |
| app/sep/snippets/schema.py                                                                                                   |       97 |        4 |       34 |        1 |     96% |159-161, 376 |
| app/sep/snippets/script\_source.py                                                                                           |       96 |        1 |       22 |        1 |     98% |       355 |
| app/sep/snippets/utils.py                                                                                                    |       32 |        0 |       10 |        0 |    100% |           |
| app/sep/sync/constants.py                                                                                                    |        4 |        0 |        0 |        0 |    100% |           |
| app/sep/sync/exceptions.py                                                                                                   |       32 |        0 |        0 |        0 |    100% |           |
| app/sep/sync/fields.py                                                                                                       |       11 |        0 |        0 |        0 |    100% |           |
| app/sep/sync/health.py                                                                                                       |       53 |        0 |        8 |        0 |    100% |           |
| app/sep/sync/models.py                                                                                                       |      408 |       34 |      104 |       18 |     88% |116-\>118, 119-127, 139-\>141, 143, 162, 168-\>170, 171-\>173, 256-\>273, 391-\>389, 480-481, 869-\>exit, 887, 901, 1008, 1022, 1081-\>exit, 1132, 1145, 1169-1171, 1204-\>exit, 1249, 1262, 1319-\>exit, 1364, 1508-1510, 1620-1622, 1627-1633, 1637 |
| app/sep/sync/syncers/mysql/payload.py                                                                                        |      176 |       47 |       54 |        5 |     70% |158-\>166, 242-246, 251-256, 269-275, 279-302, 356-\>372, 375, 396-404, 423 |
| app/sep/sync/syncers/mysql/syncer.py                                                                                         |      241 |        2 |       94 |        5 |     98% |111, 604-\>605, 716, 819-\>823, 821-\>820 |
| app/sep/sync/syncers/pmm.py                                                                                                  |      133 |        1 |       34 |        4 |     97% |107, 140-\>141, 430-\>437, 480-\>485 |
| app/sep/sync/syncers/system\_facts/payload.py                                                                                |      243 |       19 |       82 |        9 |     91% |54-\>60, 152-153, 181, 227-229, 236, 238-\>234, 249-256, 310-312, 318-320, 344, 445-\>447, 447-\>449, 553, 564 |
| app/sep/sync/syncers/system\_facts/syncer.py                                                                                 |      118 |        3 |       28 |        3 |     96% |170, 245, 256-\>254, 351 |
| app/sep/tasks.py                                                                                                             |       31 |        0 |       12 |        2 |     95% |69-\>84, 73-\>76 |
| app/sep/utils/forms.py                                                                                                       |       16 |        0 |        4 |        0 |    100% |           |
| app/sep/utils/jinja.py                                                                                                       |       61 |       10 |       10 |        1 |     79% |105, 124, 135-140, 171-172 |
| app/tasks/alembic\_ops.py                                                                                                    |       42 |        1 |        8 |        1 |     96% |       153 |
| app/tasks/alert\_hooks.py                                                                                                    |       23 |        0 |        2 |        0 |    100% |           |
| app/tasks/anonymizer/anonymize.py                                                                                            |       56 |        0 |       18 |        3 |     96% |75-\>82, 97-\>104, 118-\>122 |
| app/tasks/anonymizer/config.py                                                                                               |       30 |        1 |        6 |        1 |     94% |        81 |
| app/tasks/anonymizer/entities.py                                                                                             |       28 |        0 |        2 |        0 |    100% |           |
| app/tasks/celery.py                                                                                                          |      384 |       10 |       88 |        8 |     96% |283-\>297, 292-\>294, 509, 582-586, 771, 778-\>782, 837, 1040, 1109, 1132-1133, 1236-\>1251 |
| app/tasks/config.py                                                                                                          |       67 |        0 |       12 |        0 |    100% |           |
| app/tasks/connectivity/constants.py                                                                                          |        5 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/models.py                                                                                             |       11 |        0 |        0 |        0 |    100% |           |
| app/tasks/connectivity/payload.py                                                                                            |       70 |        1 |        8 |        1 |     97% |       170 |
| app/tasks/connectivity/routes.py                                                                                             |       16 |        0 |        2 |        0 |    100% |           |
| app/tasks/connectivity/service.py                                                                                            |      146 |        2 |       54 |        6 |     96% |173, 432-\>431, 452-\>451, 458-\>457, 473, 485-\>484 |
| app/tasks/crud.py                                                                                                            |      303 |        5 |       80 |        6 |     97% |199, 608-\>610, 611, 613, 738, 928 |
| app/tasks/db/engine.py                                                                                                       |        7 |        0 |        0 |        0 |    100% |           |
| app/tasks/db/seed.py                                                                                                         |      149 |       11 |       38 |        6 |     89% |828-\>841, 842-\>856, 1104-1125, 1136, 1148, 1181 |
| app/tasks/deps.py                                                                                                            |      110 |        3 |       30 |        0 |     98% |     64-66 |
| app/tasks/execution/exceptions.py                                                                                            |        8 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/celery/models.py                                                                               |       90 |        0 |       16 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/constants.py                                                                             |        1 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/exceptions.py                                                                            |        4 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/models.py                                                                                |      950 |       66 |      326 |       16 |     93% |198, 377, 447-450, 451-\>exit, 491, 493-\>487, 542, 585, 920, 982-\>984, 1252-\>1257, 1261, 1267, 1302-1307, 1545-\>1567, 1852, 1943, 2327-2329, 2355-2356, 2393-2394, 2428-2429, 2786, 2884-2885, 2959-2960, 2983-3039 |
| app/tasks/execution/executors/nomad/steps.py                                                                                 |       20 |        0 |        0 |        0 |    100% |           |
| app/tasks/execution/models.py                                                                                                |       73 |        2 |       14 |        0 |     98% |  233, 288 |
| app/tasks/execution/nomad\_lifecycle.py                                                                                      |       54 |        0 |       12 |        2 |     97% |145-\>148, 187-\>exit |
| app/tasks/execution/utils.py                                                                                                 |       26 |        0 |        6 |        0 |    100% |           |
| app/tasks/execution\_request\_secrets.py                                                                                     |       70 |        0 |       28 |        0 |    100% |           |
| app/tasks/hook\_resolver.py                                                                                                  |       29 |        0 |        6 |        0 |    100% |           |
| app/tasks/logs/constants.py                                                                                                  |        1 |        0 |        0 |        0 |    100% |           |
| app/tasks/logs/line\_split.py                                                                                                |       34 |        0 |        6 |        0 |    100% |           |
| app/tasks/logs/log\_reader.py                                                                                                |      140 |        8 |       62 |        6 |     92% |106, 131, 134, 181-194, 284, 294-\>286 |
| app/tasks/logs/log\_writer.py                                                                                                |      175 |       11 |       78 |       10 |     92% |145-146, 308-310, 376-377, 524, 528, 530-\>525, 532, 778, 784 |
| app/tasks/main.py                                                                                                            |       73 |        5 |       16 |        1 |     93% |209-210, 216-220 |
| app/tasks/migrations/env.py                                                                                                  |       37 |        5 |        4 |        2 |     83% |38-\>45, 65-77, 119 |
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
| app/tasks/migrations/versions/2026\_09\_04\_1842-8fdfa7869662\_encrypt\_secret\_setting\_overrides.py                        |       25 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_09\_04\_1853-36a31fac9ef7\_add\_settingoverride\_updated\_by.py                          |        9 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_09\_07\_1500-c4b8e1f7a2d9\_add\_taskhistory\_failure\_reason.py                          |       10 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_09\_09\_1930-f3b71c0d9a45\_encrypt\_execution\_request\_leaves.py                        |       10 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_09\_14\_2243-b5e17f6b3bc7\_encrypt\_credential\_url\_setting\_overrides.py               |       25 |        0 |        0 |        0 |    100% |           |
| app/tasks/migrations/versions/2026\_09\_18\_1512-794928ff7799\_unmark\_secret\_setting\_overrides.py                         |       24 |        0 |        0 |        0 |    100% |           |
| app/tasks/models.py                                                                                                          |      382 |        4 |       82 |        6 |     98% |397, 695-\>698, 702, 719-\>732, 1356-\>1358, 1367-\>1369, 1392-1393 |
| app/tasks/periodic/crud.py                                                                                                   |       31 |        0 |        0 |        0 |    100% |           |
| app/tasks/periodic/deps.py                                                                                                   |       11 |        0 |        0 |        0 |    100% |           |
| app/tasks/periodic/models.py                                                                                                 |      124 |        4 |       26 |        4 |     95% |299, 346, 360, 407 |
| app/tasks/periodic/routes.py                                                                                                 |       69 |        4 |       12 |        2 |     93% |94, 168-\>170, 190-193, 206 |
| app/tasks/periodic/utils.py                                                                                                  |       28 |        0 |        8 |        1 |     97% |   97-\>98 |
| app/tasks/routes.py                                                                                                          |      250 |       14 |       48 |        4 |     94% |155-159, 244-\>248, 281, 331-340, 347, 460, 503, 518, 678, 692, 697, 724, 727-\>729 |
| app/tasks/run\_result.py                                                                                                     |       59 |        0 |       14 |        0 |    100% |           |
| app/tasks/settings/routes.py                                                                                                 |       13 |        0 |        0 |        0 |    100% |           |
| app/tasks/task\_status.py                                                                                                    |       22 |        0 |        0 |        0 |    100% |           |
| **TOTAL**                                                                                                                    | **32435** | **1874** | **7908** |  **658** | **93%** |           |


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