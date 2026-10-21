using System.Data.Common;
using Microsoft.Data.Sqlite;
using OtterWorks.AuditService.Archive;

namespace AuditService.Tests;

public sealed class AdoArchiveEventStoreTests : IDisposable
{
    private readonly SqliteConnection _keepAlive;
    private readonly SqliteTestStore _store;

    public AdoArchiveEventStoreTests()
    {
        var connectionString = $"Data Source=archive-{Guid.NewGuid():N};Mode=Memory;Cache=Shared";
        _keepAlive = new SqliteConnection(connectionString);
        _keepAlive.Open();
        using (var command = _keepAlive.CreateCommand())
        {
            command.CommandText = """
                CREATE TABLE DOCARCH (ARCH_KEY TEXT, DOC_ID TEXT, VERSION_NO INTEGER);
                CREATE TABLE FILEAUD (AUDIT_KEY TEXT, ARCH_KEY TEXT, EVENT_TYPE TEXT);
                INSERT INTO DOCARCH VALUES ('A1  ', 'DOC-1', 1), ('A2  ', 'DOC-1', 2), ('A3  ', 'DOC-EMPTY', 1);
                INSERT INTO FILEAUD VALUES ('E1  ', 'A1  ', 'CREATE  '), ('E2  ', 'A1  ', 'READ    '), ('E3  ', 'A2  ', 'UPDATE  ');
                """;
            command.ExecuteNonQuery();
        }

        _store = new SqliteTestStore(connectionString);
    }

    public void Dispose() => _keepAlive.Dispose();

    [Fact]
    public async Task GetEventsAsync_ReturnsRowsForDocument()
    {
        var events = await _store.GetEventsAsync("DOC-1", CancellationToken.None);

        Assert.NotNull(events);
        Assert.Equal(new[] { "E1", "E2", "E3" }, events!.Select(e => e.AuditKey));
        Assert.Equal("CREATE", events[0].EventType);
        Assert.Equal("E1  ", events[0].Raw.AuditKey);
    }

    [Fact]
    public async Task GetEventsAsync_DocumentWithoutEvents_ReturnsEmptyList()
    {
        var events = await _store.GetEventsAsync("DOC-EMPTY", CancellationToken.None);

        Assert.NotNull(events);
        Assert.Empty(events!);
    }

    [Fact]
    public async Task GetEventsAsync_UnknownDocument_ReturnsNull()
    {
        Assert.Null(await _store.GetEventsAsync("NOPE", CancellationToken.None));
    }

    [Fact]
    public async Task GetEventsAsync_BindsDocIdAsParameter()
    {
        Assert.Null(await _store.GetEventsAsync("x' OR '1'='1", CancellationToken.None));
    }

    [Fact]
    public async Task GetDocumentAsync_NestsEventsUnderTheirVersion()
    {
        var versions = await _store.GetDocumentAsync("DOC-1", CancellationToken.None);

        Assert.NotNull(versions);
        Assert.Equal(new[] { "A1", "A2" }, versions!.Select(v => v.ArchKey));
        Assert.Equal(new[] { "E1", "E2" }, versions[0].Events.Select(e => e.AuditKey));
        Assert.Equal(new[] { "E3" }, versions[1].Events.Select(e => e.AuditKey));
    }

    [Fact]
    public async Task GetDocumentAsync_UnknownDocument_ReturnsNull()
    {
        Assert.Null(await _store.GetDocumentAsync("NOPE", CancellationToken.None));
    }

    [Fact]
    public async Task DatabaseErrors_SurfaceAsArchiveStoreUnavailable()
    {
        var broken = new SqliteTestStore(_keepAlive.ConnectionString, eventsSql: "SELECT * FROM MISSING_TABLE WHERE X = @docId");

        var ex = await Assert.ThrowsAsync<ArchiveStoreUnavailableException>(
            () => broken.GetEventsAsync("DOC-1", CancellationToken.None));
        Assert.StartsWith("sqlite archive query failed:", ex.Message);
        Assert.IsAssignableFrom<DbException>(ex.InnerException);
    }

    [Fact]
    public async Task PingAsync_Succeeds()
    {
        await _store.PingAsync(CancellationToken.None);
    }

    private sealed class SqliteTestStore : AdoArchiveEventStore
    {
        private const string DefaultEventsSql =
            "SELECT F.AUDIT_KEY, F.ARCH_KEY, F.EVENT_TYPE FROM DOCARCH D LEFT JOIN FILEAUD F ON F.ARCH_KEY = D.ARCH_KEY " +
            "WHERE D.DOC_ID = @docId ORDER BY F.AUDIT_KEY";

        private readonly string _connectionString;

        public SqliteTestStore(string connectionString, string eventsSql = DefaultEventsSql)
        {
            _connectionString = connectionString;
            EventsSql = eventsSql;
        }

        public override string StoreName => "sqlite";

        protected override string EventsSql { get; }

        protected override string PingSql => "SELECT 1";

        protected override string VersionsSql =>
            "SELECT ARCH_KEY, VERSION_NO FROM DOCARCH WHERE DOC_ID = @docId ORDER BY VERSION_NO";

        protected override DbConnection CreateConnection() => new SqliteConnection(_connectionString);

        protected override ArchiveEventRow MapRow(DbDataReader reader) => new()
        {
            AuditKey = Db2Text.RTrim(Str(reader, "AUDIT_KEY")),
            ArchKey = Db2Text.RTrim(Str(reader, "ARCH_KEY")),
            EventType = Db2Text.RTrim(Str(reader, "EVENT_TYPE")),
            Raw = new ArchiveEventRaw { AuditKey = Str(reader, "AUDIT_KEY"), ArchKey = Str(reader, "ARCH_KEY") },
        };

        protected override ArchiveVersionRow MapVersion(DbDataReader reader) => new()
        {
            ArchKey = Db2Text.RTrim(Str(reader, "ARCH_KEY")),
            VersionNo = Int(reader, "VERSION_NO"),
        };
    }
}
