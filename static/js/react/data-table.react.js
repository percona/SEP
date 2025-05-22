const { useMemo, useState } = React;
const {
  useTable,
  useSortBy,
  usePagination,
  useGlobalFilter
} = ReactTable;

function GlobalFilter({ globalFilter, setGlobalFilter }) {
  return (
    <div class="datatable-search input icon-left">
      <span class="material-symbols-outlined">pageview</span>
      <label aria-label="Search in table">
        <input id="filter_input" value={globalFilter || ""} onChange={e => setGlobalFilter(e.target.value)}
          placeholder="Search..."
        /></label>
    </div>
  );
}

function DataTable({ data, columns, onRowClick }) {
  const memoizedData = useMemo(() => data, [data]);
  const memoizedColumns = useMemo(() => columns, [columns]);

  const {
    getTableProps,
    getTableBodyProps,
    headerGroups,
    prepareRow,
    page,
    pageCount,
    gotoPage,
    nextPage,
    previousPage,
    canNextPage,
    canPreviousPage,
    setPageSize,
    state,
    setGlobalFilter,
    rows
  } = useTable(
    { columns: memoizedColumns, data: memoizedData, initialState: { pageSize: 10 } },
    useGlobalFilter,
    useSortBy,
    usePagination
  );

  const { globalFilter, pageIndex, pageSize } = state;
  const startRow = pageIndex * pageSize + 1;
  const endRow = Math.min(startRow + page.length - 1, rows.length);

  return (
    <div class="datatable-wrapper datatable-loading no-footer sortable searchable fixed-columns">
      <div class="datatable-top">
        <GlobalFilter globalFilter={globalFilter} setGlobalFilter={setGlobalFilter} />
        <div className="page-size-select datatable-dropdown select">
          <label>
            <span class="material-symbols-outlined">arrow_drop_down</span>
            <span class="label">Entries per page: </span>
            <select
              class="datatable-selector"
              value={pageSize}
              onChange={e => setPageSize(Number(e.target.value))}
            >
              {[10, 20, 50, 100].map(size => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div class="datatable-container">
        <table {...getTableProps()} class="datatable-table">
          <thead>
            {headerGroups.map(headerGroup => (
              <tr {...headerGroup.getHeaderGroupProps()}>
                {headerGroup.headers.map(column => {
                  const sortClass = column.isSorted
                    ? column.isSortedDesc
                      ? 'sorted-desc'
                      : 'sorted-asc'
                    : '';
                  return (
                    <th
                      {...column.getHeaderProps(column.getSortByToggleProps())}
                    >
                      <div className={sortClass}>
                        {column.render('Header')}
                      </div>
                    </th>
                  );
                })}
              </tr>
            ))}
          </thead>
          <tbody {...getTableBodyProps()}>
            {page.length === 0 ? (
              <tr>
                <td colSpan={memoizedColumns.length} style={{ textAlign: 'center', padding: '1rem', color: '#888' }}>
                  No data available
                </td>
              </tr>
            ) : (
              page.map(row => {
                prepareRow(row);
                return (
                  <tr {...row.getRowProps()} onClick={() => onRowClick(row.original)}>
                    {row.cells.map(cell => (
                      <td {...cell.getCellProps()}>{cell.render('Cell')}</td>
                    ))}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <div className="pagination-info">
        {rows.length > 0
          ? `Showing ${startRow}–${endRow} of ${rows.length} entries`
          : 'No entries found'}
      </div>
      <ul className="datatable-pagination-list pagination" style={{ marginTop: "10px", float: "right", display: "flex" }}>
        {Array.from({ length: pageCount }, (_, i) => (
          <div className={i === pageIndex ? 'datatable-active' : ''}>
            <button
              key={i}
              onClick={() => gotoPage(i)}
              style={{ fontWeight: i === pageIndex ? 'bold' : 'normal' }}
            >
              {i + 1}
            </button>
          </div>
        ))}
        <button class="pagination-prev-btn" onClick={() => previousPage()} disabled={!canPreviousPage}>
          chevron_left
        </button>
        <button class="pagination-next-btn" onClick={() => nextPage()} disabled={!canNextPage}>
          chevron_right
        </button>

      </ul>
    </div>
  );
}

