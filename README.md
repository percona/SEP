# Repository Coverage



| Name                                                                                                            |    Stmts |     Miss |   Cover |   Missing |
|---------------------------------------------------------------------------------------------------------------- | -------: | -------: | ------: | --------: |
| app/api/deps.py                                                                                                 |       48 |        0 |    100% |           |
| app/api/main.py                                                                                                 |        6 |        0 |    100% |           |
| app/api/routes/config.py                                                                                        |        9 |        0 |    100% |           |
| app/api/routes/oauth.py                                                                                         |       60 |        0 |    100% |           |
| app/api/routes/users.py                                                                                         |       21 |        0 |    100% |           |
| app/celery.py                                                                                                   |       32 |        4 |     88% | 45, 51-53 |
| app/core/alerts/config.py                                                                                       |       42 |        0 |    100% |           |
| app/core/alerts/models.py                                                                                       |       57 |        0 |    100% |           |
| app/core/alerts/providers/pagerduty.py                                                                          |       35 |        1 |     97% |       110 |
| app/core/auth/exceptions.py                                                                                     |       11 |        0 |    100% |           |
| app/core/auth/models.py                                                                                         |       63 |        1 |     98% |       170 |
| app/core/auth/providers/casdoor.py                                                                              |      123 |       61 |     50% |53, 126-127, 139, 187, 218-219, 241-248, 276-296, 304-305, 326-335, 351-352, 372-391, 409-414, 424-425, 439, 451-455, 467-471 |
| app/core/auth/utils.py                                                                                          |        5 |        0 |    100% |           |
| app/core/celery/config.py                                                                                       |       23 |        0 |    100% |           |
| app/core/celery/crud.py                                                                                         |       26 |        4 |     85% |91-98, 139 |
| app/core/celery/db.py                                                                                           |        8 |        0 |    100% |           |
| app/core/celery/deps.py                                                                                         |       10 |        0 |    100% |           |
| app/core/celery/models.py                                                                                       |       36 |        2 |     94% |   72, 135 |
| app/core/celery/utils.py                                                                                        |       31 |        2 |     94% |   92, 120 |
| app/core/config.py                                                                                              |      210 |        7 |     97% |401, 435, 519, 523, 599, 612, 653 |
| app/core/db/config.py                                                                                           |       17 |        0 |    100% |           |
| app/core/db/crud.py                                                                                             |      285 |       23 |     92% |194, 310-327, 345, 350, 367, 369, 481-484, 850-854, 1118-1119 |
| app/core/db/models.py                                                                                           |       14 |        0 |    100% |           |
| app/core/db/sql\_types.py                                                                                       |       37 |        0 |    100% |           |
| app/core/db/utils.py                                                                                            |       54 |        4 |     93% |76, 191, 220, 223 |
| app/core/exceptions.py                                                                                          |       32 |        0 |    100% |           |
| app/core/log.py                                                                                                 |       21 |        0 |    100% |           |
| app/core/middleware/log\_context.py                                                                             |       26 |        0 |    100% |           |
| app/core/middleware/security\_headers.py                                                                        |      105 |        0 |    100% |           |
| app/core/models.py                                                                                              |       20 |        0 |    100% |           |
| app/core/pagination/deps.py                                                                                     |       17 |        0 |    100% |           |
| app/core/pagination/models.py                                                                                   |       75 |        0 |    100% |           |
| app/core/pmm.py                                                                                                 |       51 |        1 |     98% |        53 |
| app/core/requests/registry.py                                                                                   |       64 |        5 |     92% |101, 112, 152, 163, 173 |
| app/core/requests/remote\_api.py                                                                                |      215 |        8 |     96% |96, 115, 414, 454-457, 465 |
| app/core/security.py                                                                                            |        4 |        0 |    100% |           |
| app/core/settings\_override/api/export.py                                                                       |       10 |        0 |    100% |           |
| app/core/settings\_override/api/models.py                                                                       |       12 |        0 |    100% |           |
| app/core/settings\_override/api/routes.py                                                                       |      234 |       28 |     88% |276, 376, 399, 518-525, 548-555, 558-567, 707-714, 744-745, 798-801, 869-871, 894, 1028, 1038-1040 |
| app/core/settings\_override/cache.py                                                                            |      118 |       13 |     89% |192-197, 210-215, 297, 360, 401, 405-412 |
| app/core/settings\_override/lifecycle.py                                                                        |       69 |        1 |     99% |       267 |
| app/core/settings\_override/manager.py                                                                          |        5 |        0 |    100% |           |
| app/core/settings\_override/models.py                                                                           |       21 |        0 |    100% |           |
| app/core/settings\_override/proxy.py                                                                            |       22 |        0 |    100% |           |
| app/core/settings\_override/registry.py                                                                         |      248 |        5 |     98% |566, 724, 756, 788, 970 |
| app/core/utils/async\_run.py                                                                                    |       13 |        0 |    100% |           |
| app/core/utils/cache.py                                                                                         |       92 |        7 |     92% |60-62, 151, 208-209, 223 |
| app/core/utils/date\_time.py                                                                                    |        8 |        0 |    100% |           |
| app/core/utils/dict.py                                                                                          |       27 |        4 |     85% |   160-163 |
| app/core/utils/fields.py                                                                                        |      148 |        5 |     97% |140, 206-207, 374, 378 |
| app/core/utils/imports.py                                                                                       |       28 |        0 |    100% |           |
| app/core/utils/iterators.py                                                                                     |       18 |        0 |    100% |           |
| app/core/utils/lazy.py                                                                                          |       31 |        0 |    100% |           |
| app/core/utils/openapi.py                                                                                       |      129 |        6 |     95% |78-79, 155, 162-163, 242 |
| app/core/utils/path.py                                                                                          |        8 |        0 |    100% |           |
| app/core/utils/pydantic.py                                                                                      |       59 |        0 |    100% |           |
| app/core/utils/serialization.py                                                                                 |        7 |        0 |    100% |           |
| app/core/utils/strings.py                                                                                       |       24 |        3 |     88% |     64-69 |
| app/inventory/config.py                                                                                         |       11 |        0 |    100% |           |
| app/inventory/constants.py                                                                                      |        2 |        0 |    100% |           |
| app/inventory/crud.py                                                                                           |       24 |        0 |    100% |           |
| app/inventory/db.py                                                                                             |        7 |        1 |     86% |        40 |
| app/inventory/deps.py                                                                                           |       24 |        3 |     88% |     38-40 |
| app/inventory/main.py                                                                                           |       28 |        9 |     68% |39-42, 73-74, 78-82 |
| app/inventory/models.py                                                                                         |       92 |        0 |    100% |           |
| app/inventory/routes/nodes.py                                                                                   |       52 |        3 |     94% |   133-135 |
| app/inventory/routes/schemas.py                                                                                 |       38 |        0 |    100% |           |
| app/inventory/routes/services.py                                                                                |       52 |        4 |     92% |125-127, 169 |
| app/inventory/routes/tables.py                                                                                  |       26 |        0 |    100% |           |
| app/main.py                                                                                                     |       78 |       27 |     65% |185-188, 193-197, 201-255 |
| app/models.py                                                                                                   |       74 |        4 |     95% |   208-213 |
| app/sep/api/constants.py                                                                                        |        2 |        0 |    100% |           |
| app/sep/api/host\_resolution.py                                                                                 |        9 |        0 |    100% |           |
| app/sep/api/models.py                                                                                           |       15 |        0 |    100% |           |
| app/sep/api/openapi.py                                                                                          |        4 |        0 |    100% |           |
| app/sep/api/router.py                                                                                           |       32 |        0 |    100% |           |
| app/sep/api/routes/app\_state.py                                                                                |       41 |       17 |     59% |174-189, 217-231 |
| app/sep/api/routes/apps.py                                                                                      |       12 |        0 |    100% |           |
| app/sep/api/routes/dashboard.py                                                                                 |       35 |        0 |    100% |           |
| app/sep/api/routes/hosts.py                                                                                     |       22 |        0 |    100% |           |
| app/sep/api/routes/schemas.py                                                                                   |        7 |        0 |    100% |           |
| app/sep/api/routes/services.py                                                                                  |       17 |        0 |    100% |           |
| app/sep/api/routes/settings.py                                                                                  |      108 |        7 |     94% |95, 100, 278-280, 290, 296 |
| app/sep/api/routes/task\_history.py                                                                             |       13 |        0 |    100% |           |
| app/sep/api/routes/task\_stats.py                                                                               |       13 |        0 |    100% |           |
| app/sep/api/task\_history\_merge.py                                                                             |       55 |        4 |     93% |57, 61-62, 113 |
| app/sep/app\_drain.py                                                                                           |       83 |        2 |     98% |  204, 210 |
| app/sep/artifact\_constants.py                                                                                  |        4 |        0 |    100% |           |
| app/sep/celery.py                                                                                               |      143 |       19 |     87% |115, 161, 199-200, 221-223, 226, 232-245, 252 |
| app/sep/clients/pmm.py                                                                                          |      247 |       10 |     96% |218, 485, 487, 561, 597-598, 732-733, 754-755 |
| app/sep/config.py                                                                                               |      227 |       10 |     96% |131, 304, 381, 398, 412, 416, 418, 420, 463, 578 |
| app/sep/connectivity.py                                                                                         |       77 |        1 |     99% |       103 |
| app/sep/crud.py                                                                                                 |       81 |        0 |    100% |           |
| app/sep/db/engine.py                                                                                            |        8 |        0 |    100% |           |
| app/sep/db/seed.py                                                                                              |       50 |       15 |     70% |     84-98 |
| app/sep/deps.py                                                                                                 |      325 |       10 |     97% |380, 383-384, 402, 991-992, 1174-1177 |
| app/sep/exceptions.py                                                                                           |       13 |        0 |    100% |           |
| app/sep/inventory.py                                                                                            |       97 |        8 |     92% |81, 92, 229, 286, 326, 363, 385, 419 |
| app/sep/main.py                                                                                                 |      204 |       17 |     92% |93-95, 137-139, 271-288, 311, 607-611 |
| app/sep/middleware/csrf.py                                                                                      |       48 |        0 |    100% |           |
| app/sep/middleware/messages/\_middleware.py                                                                     |       28 |        0 |    100% |           |
| app/sep/middleware/messages/\_utils.py                                                                          |       54 |        9 |     83% |119, 261-268 |
| app/sep/middleware/messages/config.py                                                                           |       12 |        0 |    100% |           |
| app/sep/middleware/messages/models.py                                                                           |       31 |        0 |    100% |           |
| app/sep/migrations/\_discovery.py                                                                               |       33 |        2 |     94% |   70, 103 |
| app/sep/migrations/env.py                                                                                       |       39 |        5 |     87% |68-79, 121 |
| app/sep/migrations/versions/2024\_10\_07\_1450-7f4dec8bc76a\_create\_sync\_tables.py                            |       26 |        8 |     69% |     69-76 |
| app/sep/migrations/versions/2024\_10\_08\_2047-eeac2926bbea\_remove\_task\_history\_id\_field.py                |       12 |        1 |     92% |        45 |
| app/sep/migrations/versions/2025\_08\_08\_1005-9307f0f5ee54\_create\_snippet\_table.py                          |       16 |        3 |     81% |     59-61 |
| app/sep/migrations/versions/2026\_03\_02\_1612-810c31754b54\_add\_index\_for\_syncinstance\_syncer.py           |       12 |        1 |     92% |        45 |
| app/sep/migrations/versions/2026\_05\_18\_2014-ed97b99eef38\_add\_setting\_override\_table.py                   |       18 |        4 |     78% |     81-86 |
| app/sep/migrations/versions/2026\_06\_01\_1530-e5c224619161\_add\_appstate\_table.py                            |       14 |        2 |     86% |     53-54 |
| app/sep/migrations/versions/2026\_06\_02\_1512-378c0872642f\_extend\_setting\_class\_enum\_settings\_alert.py   |       13 |        3 |     77% |     68-73 |
| app/sep/migrations/versions/2026\_06\_15\_1725-64f10ead74f6\_add\_seppluginperiodictask.py                      |       16 |        3 |     81% |     55-57 |
| app/sep/migrations/versions/2026\_06\_16\_1200-a7c4e9f1b2d3\_add\_lifecycle\_state\_to\_app\_state.py           |       26 |        0 |    100% |           |
| app/sep/migrations/versions/2026\_06\_16\_1600-b8d5f2a9c1e4\_add\_apprunningtask\_table.py                      |       16 |        3 |     81% |     54-56 |
| app/sep/models.py                                                                                               |       66 |        1 |     98% |       247 |
| app/sep/periodic\_tasks.py                                                                                      |       41 |        0 |    100% |           |
| app/sep/plugins/alert\_troubleshooting/api\_routes.py                                                           |       23 |        4 |     83% |64-65, 73-80 |
| app/sep/plugins/alert\_troubleshooting/deps.py                                                                  |      135 |       18 |     87% |122, 237, 259-261, 280, 364, 388-394, 418-420, 444-447, 474 |
| app/sep/plugins/alert\_troubleshooting/models.py                                                                |        7 |        0 |    100% |           |
| app/sep/plugins/alert\_troubleshooting/routes.py                                                                |       67 |        5 |     93% |143-148, 199-200 |
| app/sep/plugins/alert\_troubleshooting/schema.py                                                                |        2 |        0 |    100% |           |
| app/sep/plugins/alerts/api\_routes.py                                                                           |      121 |       16 |     87% |179, 195-198, 242-252 |
| app/sep/plugins/alerts/config.py                                                                                |       19 |        0 |    100% |           |
| app/sep/plugins/alerts/crud.py                                                                                  |        6 |        0 |    100% |           |
| app/sep/plugins/alerts/deps.py                                                                                  |       91 |        0 |    100% |           |
| app/sep/plugins/alerts/loader.py                                                                                |       22 |        0 |    100% |           |
| app/sep/plugins/alerts/migrations/versions/2026\_04\_20\_1817-d21ad387df7a\_create\_alert\_backup\_table.py     |       14 |        0 |    100% |           |
| app/sep/plugins/alerts/models.py                                                                                |       22 |        0 |    100% |           |
| app/sep/plugins/alerts/restore.py                                                                               |      102 |        3 |     97% |95, 100, 169 |
| app/sep/plugins/alerts/routes.py                                                                                |      111 |       12 |     89% |97-99, 280-281, 321-339 |
| app/sep/plugins/alerts/schemas.py                                                                               |       25 |        0 |    100% |           |
| app/sep/plugins/alters/api\_routes.py                                                                           |       58 |        8 |     86% |80, 97, 142-147, 189-192, 199-204 |
| app/sep/plugins/alters/deps.py                                                                                  |      304 |        9 |     97% |626, 701-702, 804, 827-828, 980, 991, 993 |
| app/sep/plugins/alters/models.py                                                                                |      114 |        2 |     98% |   57, 261 |
| app/sep/plugins/alters/pre\_checks.py                                                                           |      236 |      236 |      0% |    27-638 |
| app/sep/plugins/alters/routes.py                                                                                |      105 |        2 |     98% |   303-306 |
| app/sep/plugins/alters/schema.py                                                                                |        6 |        0 |    100% |           |
| app/sep/plugins/archives/api\_routes.py                                                                         |       31 |        0 |    100% |           |
| app/sep/plugins/archives/constants.py                                                                           |        5 |        0 |    100% |           |
| app/sep/plugins/archives/deps.py                                                                                |      114 |        2 |     98% |  428, 460 |
| app/sep/plugins/archives/models.py                                                                              |       75 |        0 |    100% |           |
| app/sep/plugins/archives/payload                                                                                |      195 |      135 |     31% |44-235, 240-246, 295, 300-309, 385-400, 405-409, 413 |
| app/sep/plugins/archives/routes.py                                                                              |       91 |        3 |     97% |143, 145, 147 |
| app/sep/plugins/archives/schema.py                                                                              |        5 |        0 |    100% |           |
| app/sep/plugins/atw/api\_routes.py                                                                              |       42 |        0 |    100% |           |
| app/sep/plugins/atw/models.py                                                                                   |       34 |        0 |    100% |           |
| app/sep/plugins/atw/routes.py                                                                                   |       24 |        9 |     62% |     49-80 |
| app/sep/plugins/atw/schema.py                                                                                   |       13 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/api\_routes.py                                                                    |       42 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/deps.py                                                                           |      165 |       50 |     70% |88, 111-124, 151-177, 240, 448-467, 477-478, 553, 572-574, 607 |
| app/sep/plugins/backup\_mongo/models.py                                                                         |      129 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/api\_routes.py                                                            |       37 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/restore/deps.py                                                                   |      223 |       41 |     82% |223, 290-311, 341, 401-402, 440, 675-689, 703-704, 773, 896-907, 942 |
| app/sep/plugins/backup\_mongo/restore/models.py                                                                 |      141 |        7 |     95% |53-55, 57, 60-64, 479 |
| app/sep/plugins/backup\_mongo/restore/routes.py                                                                 |      140 |       36 |     74% |71-72, 80-81, 106-111, 121-126, 143-144, 147-152, 173, 196, 214, 245-246, 252, 289-290, 295-296, 321-322, 352-361, 400-402 |
| app/sep/plugins/backup\_mongo/restore/schema.py                                                                 |        5 |        0 |    100% |           |
| app/sep/plugins/backup\_mongo/routes.py                                                                         |       83 |       35 |     58% |66, 147-208, 229-238, 252-255 |
| app/sep/plugins/backup\_mongo/schema.py                                                                         |        9 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/api\_routes.py                                                                       |       40 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/deps.py                                                                              |       95 |       11 |     88% |195-197, 286-288, 351, 387-395 |
| app/sep/plugins/backup\_pg/models.py                                                                            |       57 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/routes.py                                                                            |       62 |        0 |    100% |           |
| app/sep/plugins/backup\_pg/schema.py                                                                            |        4 |        0 |    100% |           |
| app/sep/plugins/checksums/app.py                                                                                |       15 |        0 |    100% |           |
| app/sep/plugins/checksums/deps.py                                                                               |      105 |       60 |     43% |68-79, 95-133, 334-336, 353-358, 374-401, 414-441, 452, 482 |
| app/sep/plugins/checksums/models.py                                                                             |       66 |        0 |    100% |           |
| app/sep/plugins/checksums/payload.py                                                                            |       32 |        0 |    100% |           |
| app/sep/plugins/checksums/routes.py                                                                             |       65 |       32 |     51% |60-61, 108-162, 182-190, 205-211, 227-228 |
| app/sep/plugins/checksums/views.py                                                                              |        4 |        0 |    100% |           |
| app/sep/plugins/dipper/api\_routes.py                                                                           |       64 |        4 |     94% |79-80, 135-136 |
| app/sep/plugins/dipper/constants.py                                                                             |       10 |        0 |    100% |           |
| app/sep/plugins/dipper/deps.py                                                                                  |      185 |       40 |     78% |128-130, 151-152, 175-180, 194-195, 246-275, 338-341, 372, 483, 485, 487, 575, 614 |
| app/sep/plugins/dipper/models.py                                                                                |       14 |        0 |    100% |           |
| app/sep/plugins/dipper/payloads/pcs-collect-pmm-mysql.py                                                        |      303 |      259 |     15% |   261-875 |
| app/sep/plugins/dipper/payloads/pcs-collect-pmm-valkey.py                                                       |      225 |      192 |     15% |   155-658 |
| app/sep/plugins/dipper/routes.py                                                                                |       67 |       41 |     39% |94-199, 216-221 |
| app/sep/plugins/dipper/schema.py                                                                                |       38 |        1 |     97% |       236 |
| app/sep/plugins/framework/api.py                                                                                |      233 |       11 |     95% |170-175, 668-669, 691-696, 788, 794, 809 |
| app/sep/plugins/framework/apps.py                                                                               |      176 |        8 |     95% |368, 373, 388, 406, 450, 455, 462, 598 |
| app/sep/plugins/framework/base.py                                                                               |       25 |        2 |     92% |    79, 86 |
| app/sep/plugins/framework/cascade.py                                                                            |      183 |        0 |    100% |           |
| app/sep/plugins/framework/conformance.py                                                                        |       74 |        5 |     93% |65, 151, 222, 235, 239 |
| app/sep/plugins/framework/connectivity.py                                                                       |       24 |        0 |    100% |           |
| app/sep/plugins/framework/deprecation.py                                                                        |       19 |        0 |    100% |           |
| app/sep/plugins/framework/deps.py                                                                               |        7 |        0 |    100% |           |
| app/sep/plugins/framework/form\_dsl/conformance.py                                                              |       46 |        9 |     80% |65, 69, 85-93 |
| app/sep/plugins/framework/form\_dsl/derivation.py                                                               |      285 |       25 |     91% |211, 228, 325, 341, 346, 356, 369-371, 384-386, 390, 394, 411, 417, 432, 435, 443, 449-450, 452, 497, 503, 640 |
| app/sep/plugins/framework/form\_dsl/markers.py                                                                  |       77 |        0 |    100% |           |
| app/sep/plugins/framework/form\_dsl/model.py                                                                    |       13 |        1 |     92% |        62 |
| app/sep/plugins/framework/payload.py                                                                            |       76 |        0 |    100% |           |
| app/sep/plugins/framework/registry.py                                                                           |       47 |        1 |     98% |       139 |
| app/sep/plugins/framework/responses.py                                                                          |       43 |        0 |    100% |           |
| app/sep/plugins/framework/rules.py                                                                              |      534 |        7 |     99% |331, 336, 341, 553, 869, 1356, 1376 |
| app/sep/plugins/framework/schema.py                                                                             |      338 |        2 |     99% |1034, 1430 |
| app/sep/plugins/framework/task\_status.py                                                                       |       29 |        0 |    100% |           |
| app/sep/plugins/inventory/api\_routes.py                                                                        |       64 |        0 |    100% |           |
| app/sep/plugins/inventory/deps.py                                                                               |      140 |       13 |     91% |275-299, 411-416, 459, 466 |
| app/sep/plugins/inventory/models.py                                                                             |       29 |        1 |     97% |        93 |
| app/sep/plugins/inventory/routes.py                                                                             |      173 |        0 |    100% |           |
| app/sep/plugins/inventory/schema.py                                                                             |        8 |        0 |    100% |           |
| app/sep/plugins/inventory/sync.py                                                                               |       40 |        0 |    100% |           |
| app/sep/plugins/mysql\_backups/api\_routes.py                                                                   |       37 |        0 |    100% |           |
| app/sep/plugins/mysql\_backups/deps.py                                                                          |      107 |        6 |     94% |201, 248, 263, 266-267, 384 |
| app/sep/plugins/mysql\_backups/models.py                                                                        |      139 |        3 |     98% |308, 342, 357 |
| app/sep/plugins/mysql\_backups/restore/deps.py                                                                  |       69 |       11 |     84% |78-84, 103, 119, 204, 220-225, 258 |
| app/sep/plugins/mysql\_backups/restore/models.py                                                                |       73 |        1 |     99% |       198 |
| app/sep/plugins/mysql\_backups/restore/routes.py                                                                |       65 |        8 |     88% |146-147, 176-185, 222-224 |
| app/sep/plugins/mysql\_backups/routes.py                                                                        |       77 |        6 |     92% |77, 185-186, 239-244 |
| app/sep/plugins/mysql\_backups/schema.py                                                                        |       18 |        0 |    100% |           |
| app/sep/plugins/report/api\_routes.py                                                                           |       33 |        0 |    100% |           |
| app/sep/plugins/report/deps.py                                                                                  |       28 |        0 |    100% |           |
| app/sep/plugins/report/models.py                                                                                |      111 |        0 |    100% |           |
| app/sep/plugins/report/routes.py                                                                                |       39 |        0 |    100% |           |
| app/sep/plugins/report/schemas.py                                                                               |        6 |        6 |      0% |     18-43 |
| app/sep/plugins/report/service.py                                                                               |      378 |       16 |     96% |126, 130, 331, 345-346, 407, 444-445, 447, 451, 553, 558, 566, 575, 638, 645 |
| app/sep/plugins/snippets/api\_routes.py                                                                         |      100 |        8 |     92% |123-125, 299, 302-303, 351, 382 |
| app/sep/plugins/snippets/deps.py                                                                                |      139 |       26 |     81% |68, 139-141, 177-180, 208, 239, 268-270, 320-336, 490, 522-529 |
| app/sep/plugins/snippets/models.py                                                                              |       29 |        0 |    100% |           |
| app/sep/plugins/snippets/routes.py                                                                              |      100 |       49 |     51% |81-83, 112, 122, 135-138, 172-182, 186-222, 233-248, 267-306 |
| app/sep/plugins/snippets/schema.py                                                                              |       56 |        4 |     93% |137-139, 246 |
| app/sep/plugins/tasks/api\_routes.py                                                                            |       25 |        0 |    100% |           |
| app/sep/plugins/tasks/deps.py                                                                                   |        5 |        0 |    100% |           |
| app/sep/plugins/tasks/models.py                                                                                 |       30 |        1 |     97% |       138 |
| app/sep/plugins/tasks/routes.py                                                                                 |       56 |        0 |    100% |           |
| app/sep/plugins/tasks/schema.py                                                                                 |        2 |        0 |    100% |           |
| app/sep/routes/artifacts.py                                                                                     |       29 |        1 |     97% |        67 |
| app/sep/routes/download\_files.py                                                                               |       43 |        0 |    100% |           |
| app/sep/routes/execution\_events.py                                                                             |       14 |        0 |    100% |           |
| app/sep/routes/inventory\_ajax.py                                                                               |       24 |        0 |    100% |           |
| app/sep/routes/periodic\_tasks.py                                                                               |       31 |        1 |     97% |        83 |
| app/sep/routes/stop\_task.py                                                                                    |       19 |        0 |    100% |           |
| app/sep/routes/stream\_logs.py                                                                                  |       78 |       29 |     63% |86, 91-98, 109-132, 185-207 |
| app/sep/snippets/config.py                                                                                      |      130 |       20 |     85% |124, 196-205, 217, 267, 349-354, 435, 446, 462-465 |
| app/sep/snippets/crud.py                                                                                        |       15 |        0 |    100% |           |
| app/sep/snippets/forms.py                                                                                       |      248 |       10 |     96% |181, 672-675, 867, 869, 880, 988, 995 |
| app/sep/snippets/models/meta.py                                                                                 |      153 |        1 |     99% |       303 |
| app/sep/snippets/models/snippet.py                                                                              |      365 |       17 |     95% |277-278, 379, 382, 631-643, 724-726, 802-804, 887 |
| app/sep/snippets/utils.py                                                                                       |       32 |        0 |    100% |           |
| app/sep/sync/exceptions.py                                                                                      |       25 |        0 |    100% |           |
| app/sep/sync/models.py                                                                                          |      368 |       48 |     87% |81-90, 125, 273-275, 336, 396-397, 544, 576, 592, 612-618, 716, 730, 750-751, 831, 845, 867-868, 949, 962, 986-988, 1093-1094, 1169, 1313-1315, 1324, 1422-1424, 1429-1435, 1439 |
| app/sep/sync/syncers/mysql/payload.py                                                                           |      175 |       47 |     73% |240-244, 249-254, 267-273, 277-300, 373, 394-402, 421 |
| app/sep/sync/syncers/mysql/syncer.py                                                                            |      222 |        9 |     96% |112, 579, 601, 619, 708-717 |
| app/sep/sync/syncers/pmm.py                                                                                     |       93 |       19 |     80% |83-87, 107-110, 121, 176-184, 232, 236-252, 344 |
| app/sep/sync/syncers/system\_facts/payload.py                                                                   |      235 |       19 |     92% |147-148, 176, 222-224, 231, 244-251, 282-284, 290-292, 316, 522, 533 |
| app/sep/sync/syncers/system\_facts/syncer.py                                                                    |      118 |        7 |     94% |104, 169-170, 245, 310-311, 350 |
| app/sep/tasks.py                                                                                                |       31 |        0 |    100% |           |
| app/sep/utils/decorators.py                                                                                     |       10 |        0 |    100% |           |
| app/sep/utils/forms.py                                                                                          |       20 |        0 |    100% |           |
| app/sep/utils/jinja.py                                                                                          |       61 |       10 |     84% |105, 124, 135-140, 171-172 |
| app/sep/utils/static.py                                                                                         |       10 |        0 |    100% |           |
| app/tasks/anonymizer/anonymize.py                                                                               |       50 |        0 |    100% |           |
| app/tasks/anonymizer/config.py                                                                                  |       27 |        1 |     96% |        68 |
| app/tasks/anonymizer/entities.py                                                                                |       28 |        0 |    100% |           |
| app/tasks/celery.py                                                                                             |      290 |        8 |     97% |301, 335-337, 644, 715, 738-739 |
| app/tasks/config.py                                                                                             |       25 |        0 |    100% |           |
| app/tasks/connectivity/constants.py                                                                             |        4 |        0 |    100% |           |
| app/tasks/connectivity/models.py                                                                                |       11 |        0 |    100% |           |
| app/tasks/connectivity/payload.py                                                                               |       68 |        1 |     99% |       162 |
| app/tasks/connectivity/routes.py                                                                                |       16 |        0 |    100% |           |
| app/tasks/connectivity/service.py                                                                               |      103 |        2 |     98% |  178, 348 |
| app/tasks/crud.py                                                                                               |      208 |        1 |     99% |       445 |
| app/tasks/db/engine.py                                                                                          |        8 |        0 |    100% |           |
| app/tasks/db/seed.py                                                                                            |       65 |       25 |     62% |489-547, 576 |
| app/tasks/deps.py                                                                                               |      101 |        3 |     97% |     61-63 |
| app/tasks/execution/exceptions.py                                                                               |        8 |        0 |    100% |           |
| app/tasks/execution/executors/celery/models.py                                                                  |       82 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/exceptions.py                                                               |        4 |        0 |    100% |           |
| app/tasks/execution/executors/nomad/models.py                                                                   |      660 |      151 |     77% |104-106, 113, 153, 171-174, 194, 237, 425, 709, 715, 848, 850, 979, 1021-1051, 1072-1086, 1112-1122, 1143-1146, 1225-1227, 1253-1254, 1291-1292, 1326-1327, 1494-1543, 1551-1552, 1556, 1580-1624, 1681-1682, 1754-1755, 1773-1825 |
| app/tasks/execution/models.py                                                                                   |       65 |        0 |    100% |           |
| app/tasks/execution/nomad\_lifecycle.py                                                                         |       52 |        0 |    100% |           |
| app/tasks/execution/utils.py                                                                                    |       26 |        0 |    100% |           |
| app/tasks/logs/log\_reader.py                                                                                   |      140 |        8 |     94% |106, 131, 134, 181-194, 284 |
| app/tasks/logs/log\_writer.py                                                                                   |      123 |        8 |     93% |116, 226-227, 349, 353, 357, 537, 543 |
| app/tasks/main.py                                                                                               |       70 |        9 |     87% |100-122, 200-201, 207-211 |
| app/tasks/migrations/env.py                                                                                     |       36 |        5 |     86% |64-75, 116 |
| app/tasks/migrations/versions/2024\_09\_18\_1542-04f50684d5d7\_create\_task\_and\_taskhistory\_tables.py        |       34 |       12 |     65% |     77-88 |
| app/tasks/migrations/versions/2024\_10\_24\_1528-7920c0e4aa23\_update\_taskbackendenum.py                       |       14 |        2 |     86% |     50-51 |
| app/tasks/migrations/versions/2024\_11\_16\_1508-d15d7ea76f80\_use\_enum\_for\_task\_owner.py                   |       16 |        3 |     81% |     50-55 |
| app/tasks/migrations/versions/2025\_05\_03\_1359-064c3cec8450\_update\_task\_owner\_enum.py                     |       14 |        2 |     86% |     49-50 |
| app/tasks/migrations/versions/2025\_05\_03\_1454-80e592531cd7\_add\_started\_at\_and\_finished\_at\_fields\_.py |       35 |       18 |     49% |61-69, 77-115 |
| app/tasks/migrations/versions/2025\_05\_15\_1933-bec093f02c15\_add\_field\_sync\_in\_progress\_started\_at\_.py |       14 |        2 |     86% |     46-47 |
| app/tasks/migrations/versions/2025\_05\_20\_1144-68379e926e7c\_update\_taskhistory\_status\_enum.py             |       14 |        2 |     86% |     50-51 |
| app/tasks/migrations/versions/2025\_05\_21\_1144-36f2b569e7bb\_create\_dispatchlock\_table.py                   |       14 |        2 |     86% |     52-53 |
| app/tasks/migrations/versions/2025\_06\_11\_1021-b4f0b7b50441\_add\_alert\_on\_fail\_field\_to\_task.py         |       12 |        1 |     92% |        44 |
| app/tasks/migrations/versions/2025\_08\_05\_2350-19605d228fa3\_add\_anonymize\_mask\_field.py                   |       12 |        1 |     92% |        45 |
| app/tasks/migrations/versions/2025\_08\_07\_1757-8f61364b2c2c\_make\_task\_owner\_normal\_string.py             |       14 |        2 |     86% |     46-47 |
| app/tasks/migrations/versions/2025\_08\_22\_2153-d39d37d3dcdc\_migrate\_legacy\_generatedtasks.py               |      108 |       79 |     27% |59-62, 66-67, 71-74, 78-81, 85-113, 117-128, 155-166, 177, 214-221, 225-227, 231-255 |
| app/tasks/migrations/versions/2025\_09\_16\_1745-3b15a15ac473\_add\_anonymize\_mask\_field\_to\_taskhistory.py  |       16 |        3 |     81% |     49-51 |
| app/tasks/migrations/versions/2025\_09\_25\_0448-4e346919fc0f\_add\_output\_files\_path\_to\_task.py            |       12 |        1 |     92% |        45 |
| app/tasks/migrations/versions/2025\_10\_07\_1752-0b852d9798ef\_add\_user\_tracking\_fields.py                   |       16 |        3 |     81% |     47-49 |
| app/tasks/migrations/versions/2025\_12\_29\_1001-add\_filelock\_requirement\_to\_backup\_tasks.py               |       87 |       64 |     26% |54-73, 78-85, 105-136, 143-187 |
| app/tasks/migrations/versions/2026\_03\_04\_2149-bb3edb973603\_.py                                              |       13 |        2 |     85% |     53-54 |
| app/tasks/migrations/versions/2026\_04\_14\_1000-taskhistory\_log\_create\_taskhistory\_log\_tables.py          |       17 |        4 |     76% |   148-156 |
| app/tasks/migrations/versions/2026\_04\_14\_1752-9ebd648709e8\_add\_execution\_request\_json\_indexes.py        |       27 |       12 |     56% |64-69, 85-94 |
| app/tasks/migrations/versions/2026\_04\_14\_2218-89e80a316a28\_convert\_execution\_request\_to\_jsonb.py        |       18 |        7 |     61% |62-67, 74-78 |
| app/tasks/migrations/versions/2026\_04\_21\_1701-e42ce8324da7\_add\_stale\_to\_taskhistory\_status\_enum.py     |       13 |        2 |     85% |     55-56 |
| app/tasks/migrations/versions/2026\_05\_18\_2014-fafdb0445092\_add\_setting\_override\_table.py                 |       18 |        4 |     78% |     81-86 |
| app/tasks/migrations/versions/2026\_05\_20\_1500-7d1232c0e3ce\_coerce\_alters\_recursion\_method\_host.py       |       37 |       15 |     59% |     75-91 |
| app/tasks/migrations/versions/2026\_06\_02\_1512-6d4cfd37bd3a\_extend\_setting\_class\_enum\_settings\_alert.py |       13 |        3 |     77% |     68-73 |
| app/tasks/models.py                                                                                             |      299 |        3 |     99% |607, 1053-1054 |
| app/tasks/periodic/crud.py                                                                                      |       26 |        0 |    100% |           |
| app/tasks/periodic/deps.py                                                                                      |       11 |        0 |    100% |           |
| app/tasks/periodic/models.py                                                                                    |      103 |        5 |     95% |196, 231, 285, 301, 370 |
| app/tasks/periodic/routes.py                                                                                    |       56 |        4 |     93% |64-68, 133-136 |
| app/tasks/routes.py                                                                                             |      227 |       38 |     83% |139-143, 200, 221-228, 260, 316-317, 323, 367-368, 393-394, 433-434, 453, 593, 617, 630-644, 665-678, 694-695 |
| app/tasks/settings/routes.py                                                                                    |       10 |        0 |    100% |           |
| **TOTAL**                                                                                                       | **21385** | **2670** | **88%** |           |


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