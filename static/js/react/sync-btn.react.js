function SyncButton({ loading, canSync, onClick }) {
  if (!canSync) return null;
  return (
    <button
      onClick={onClick}
      disabled={loading}
      className="icons"
      style={{ display: 'inline' }}
    >
      <span
        className="material-symbols-outlined"
        style={{
          animation: loading ? 'spin 1s linear infinite' : 'none',
          display: 'inline-block'
        }}
      >
        autorenew
      </span>
    </button>
  );
}