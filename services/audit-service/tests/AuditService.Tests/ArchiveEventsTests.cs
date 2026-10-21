using System.Text;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Http.HttpResults;
using Microsoft.Extensions.Logging;
using Moq;
using OtterWorks.AuditService.Archive;
using OtterWorks.AuditService.Controllers;

namespace AuditService.Tests;

public class Db2TextTests
{
    [Fact]
    public void RTrim_RemovesOnlyTrailingSpaces()
    {
        Assert.Equal("  LOPEZ, M.", Db2Text.RTrim("  LOPEZ, M.      "));
        Assert.Equal("A\t", Db2Text.RTrim("A\t  "));
        Assert.Equal(string.Empty, Db2Text.RTrim(null));
    }

    [Fact]
    public void Decimal8_AlwaysHasEightFractionDigits()
    {
        Assert.Equal("1234.50000000", Db2Text.Decimal8(1234.5m));
        Assert.Equal("0.00000000", Db2Text.Decimal8(0m));
        Assert.Equal("-0.12345678", Db2Text.Decimal8(-0.12345678m));
    }

    [Fact]
    public void Timestamp12_FromDb2CharText_IsUnchanged()
    {
        Assert.Equal("2015-07-02-08.00.00.000000000001", Db2Text.Timestamp12("2015-07-02-08.00.00.000000000001"));
    }

    [Fact]
    public void Timestamp12_FromIsoText_PadsFraction()
    {
        Assert.Equal("2016-03-01-10.15.30.123456000000", Db2Text.Timestamp12("2016-03-01 10:15:30.123456"));
        Assert.Equal("2016-03-01-10.15.30.000000000000", Db2Text.Timestamp12("2016-03-01 10:15:30"));
    }

    [Fact]
    public void Timestamp12_FromDateTime2AndNanosTail_ReconstructsExactly()
    {
        var dt = new DateTime(2016, 3, 1, 10, 15, 30).AddTicks(1234567);
        Assert.Equal("2016-03-01-10.15.30.123456789012", Db2Text.Timestamp12(dt, 89012));
        Assert.Equal("2015-07-02-08.00.00.000000000001", Db2Text.Timestamp12(new DateTime(2015, 7, 2, 8, 0, 0), 1));
    }

    [Fact]
    public void DecodeCp037_DecodesEbcdic()
    {
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        var bytes = Encoding.GetEncoding(37).GetBytes("LOPEZ, M.      ");
        Assert.Equal("LOPEZ, M.      ", Db2Text.DecodeCp037(bytes));
    }
}

public class ArchiveStoreOptionsTests
{
    private static ArchiveStoreOptions Opts(params (string, string)[] env)
    {
        var map = env.ToDictionary(e => e.Item1, e => e.Item2);
        return ArchiveStoreOptions.FromEnvironment(k => map.TryGetValue(k, out var v) ? v : null);
    }

    [Fact]
    public void UnsetStore_IsOff()
    {
        Assert.Equal(ArchiveStoreType.Off, Opts().StoreType);
    }

    [Theory]
    [InlineData("db2", ArchiveStoreType.Db2)]
    [InlineData("AzureSQL", ArchiveStoreType.AzureSql)]
    [InlineData("PostgreSQL", ArchiveStoreType.PostgreSql)]
    [InlineData("postgres", ArchiveStoreType.PostgreSql)]
    [InlineData("oracle", ArchiveStoreType.Invalid)]
    public void StoreType_IsCaseInsensitive(string value, ArchiveStoreType expected)
    {
        Assert.Equal(expected, Opts(("ARCHIVE_STORE", value)).StoreType);
    }

    [Fact]
    public void AzureSql_ManagedIdentity_DoesNotNeedPassword()
    {
        var o = Opts(("ARCHIVE_STORE", "azuresql"), ("AZSQL_SERVER", "sql-x"), ("AZSQL_DATABASE", "db"),
            ("AZSQL_AUTH", "managed-identity"), ("AZURE_CLIENT_ID", "cid"));
        Assert.True(o.AzsqlComplete);
        Assert.Contains("sql-x.database.windows.net", o.AzsqlConnectionString);
        Assert.Contains("Active Directory Managed Identity", o.AzsqlConnectionString);
        Assert.DoesNotContain("Password", o.AzsqlConnectionString);
    }

    [Fact]
    public void Postgres_ConnectionStringAndCompleteness()
    {
        var o = Opts(("ARCHIVE_STORE", "postgresql"), ("PG_HOST", "pg.internal"), ("PG_DATABASE", "otterworks_x1"),
            ("PG_USER", "ldm_reader"), ("PG_PASSWORD", "s3cret"), ("PG_SSLMODE", "require"));
        Assert.True(o.PgComplete);
        Assert.Equal("Host=pg.internal;Port=5432;Database=otterworks_x1;Username=ldm_reader;Password=s3cret;SSL Mode=require;Timeout=30;",
            o.PgConnectionString);
        Assert.False(Opts(("ARCHIVE_STORE", "postgresql"), ("PG_HOST", "pg.internal")).PgComplete);
    }

    [Fact]
    public void Postgres_Timestamp12_RebuildsFromMicrosPlusSixDigitTail()
    {
        var ts = new DateTime(2016, 3, 1, 10, 15, 30).AddTicks(1234560);
        Assert.Equal("2016-03-01-10.15.30.123456789012", Db2Text.Timestamp12FromMicros(ts, 789012));
        Assert.Equal(Db2Text.Timestamp12(new DateTime(2016, 3, 1, 10, 15, 30).AddTicks(1234567), 89012),
            Db2Text.Timestamp12FromMicros(ts, 789012));
        Assert.Equal("2015-07-02-08.00.00.000000000001", Db2Text.Timestamp12FromMicros(new DateTime(2015, 7, 2, 8, 0, 0), 1));
    }

    [Fact]
    public void Db2_IncompleteWithoutPassword()
    {
        var o = Opts(("ARCHIVE_STORE", "db2"), ("DB2_HOST", "h"), ("DB2_DATABASE", "d"), ("DB2_USER", "u"));
        Assert.False(o.Db2Complete);
        Assert.Equal("50000", o.Db2Port);
    }
}

public class ArchiveControllerTests
{
    private static ArchiveStoreRegistry Registry(ArchiveStoreOptions options, IArchiveEventStore? store = null) =>
        new(options, Mock.Of<ILogger<ArchiveStoreRegistry>>(), _ => store ?? Mock.Of<IArchiveEventStore>());

    private static ArchiveStoreOptions Db2Options() => new()
    {
        Store = "db2",
        Db2Host = "h",
        Db2Database = "d",
        Db2User = "u",
        Db2Password = "p",
    };

    [Fact]
    public async Task FeatureOff_Returns404WithHint()
    {
        var result = await ArchiveController.GetEvents("DOC1", Registry(new ArchiveStoreOptions()), default);
        Assert.Equal(StatusCodes.Status404NotFound, ((IStatusCodeHttpResult)result).StatusCode);
        Assert.Contains("ARCHIVE_STORE=db2", System.Text.Json.JsonSerializer.Serialize(((IValueHttpResult)result).Value));
    }

    [Fact]
    public async Task InvalidStore_Returns503_AndServiceStillConstructs()
    {
        var registry = Registry(new ArchiveStoreOptions { Store = "oracle" });
        Assert.NotNull(registry.ConfigurationError);
        var result = await ArchiveController.GetEvents("DOC1", registry, default);
        Assert.Equal(StatusCodes.Status503ServiceUnavailable, ((IStatusCodeHttpResult)result).StatusCode);
    }

    [Fact]
    public async Task IncompleteDb2Config_Returns503()
    {
        var result = await ArchiveController.GetEvents("DOC1", Registry(new ArchiveStoreOptions { Store = "db2" }), default);
        Assert.Equal(StatusCodes.Status503ServiceUnavailable, ((IStatusCodeHttpResult)result).StatusCode);
    }

    [Fact]
    public async Task UnknownDocument_Returns404()
    {
        var store = new Mock<IArchiveEventStore>();
        store.Setup(s => s.GetEventsAsync("NOPE", It.IsAny<CancellationToken>()))
            .ReturnsAsync((IReadOnlyList<ArchiveEventRow>?)null);
        var result = await ArchiveController.GetEvents("NOPE", Registry(Db2Options(), store.Object), default);
        Assert.Equal(StatusCodes.Status404NotFound, ((IStatusCodeHttpResult)result).StatusCode);
    }

    [Fact]
    public async Task KnownDocument_ReturnsEventsWithStoreName()
    {
        var store = new Mock<IArchiveEventStore>();
        store.SetupGet(s => s.StoreName).Returns("azuresql");
        store.Setup(s => s.GetEventsAsync("DOC42", It.IsAny<CancellationToken>()))
            .ReturnsAsync(new List<ArchiveEventRow>
            {
                new() { AuditKey = "FA000000000000000123", EventType = "VIEW", EventTs = "2015-07-02-08.00.00.000000000001" },
            });
        var result = await ArchiveController.GetEvents("DOC42", Registry(Db2Options(), store.Object), default);
        var ok = Assert.IsType<Ok<ArchiveEventsResponse>>(result);
        Assert.Equal("DOC42", ok.Value!.DocId);
        Assert.Equal("azuresql", ok.Value.Store);
        Assert.Single(ok.Value.Events);
        Assert.Equal("2015-07-02-08.00.00.000000000001", ok.Value.Events[0].EventTs);
    }

    [Fact]
    public async Task GetDocument_ReturnsContractShape_VersionsWithNestedEvents()
    {
        var store = new Mock<IArchiveEventStore>();
        store.SetupGet(s => s.StoreName).Returns("db2");
        store.Setup(s => s.GetDocumentAsync("DOC42", It.IsAny<CancellationToken>()))
            .ReturnsAsync(new List<ArchiveVersionRow>
            {
                new()
                {
                    ArchKey = "DA00000000000042", VersionNo = 3, RetentionClass = "FIN7",
                    LastAccessTs = "2016-03-01-10.15.30.123456789012", StorageCharge = "1234.50000000",
                    OwnerName = "LOPEZ, M.", DispositionDt = "2023-03-01",
                    Events = { new() { AuditKey = "FA000000000000000123", EventType = "VIEW" } },
                },
            });
        var result = await ArchiveController.GetDocument("DOC42", Registry(Db2Options(), store.Object), default);
        var ok = Assert.IsType<Ok<ArchiveDocumentResponse>>(result);
        Assert.Equal("db2", ok.Value!.Store);
        var version = Assert.Single(ok.Value.Versions);
        Assert.Equal(3, version.VersionNo);
        Assert.Equal("1234.50000000", version.StorageCharge);
        Assert.Equal("FA000000000000000123", Assert.Single(version.Events).AuditKey);
    }

    [Fact]
    public async Task GetDocument_UnknownDocument_Is404()
    {
        var store = new Mock<IArchiveEventStore>();
        store.Setup(s => s.GetDocumentAsync("NOPE", It.IsAny<CancellationToken>()))
            .ReturnsAsync((IReadOnlyList<ArchiveVersionRow>?)null);
        var result = await ArchiveController.GetDocument("NOPE", Registry(Db2Options(), store.Object), default);
        Assert.Equal(404, Assert.IsAssignableFrom<IStatusCodeHttpResult>(result).StatusCode);
    }

    [Theory]
    [InlineData("20230301", "2023-03-01")]
    [InlineData("20230301  ", "2023-03-01")]
    [InlineData("\0\0\0\0\0\0\0\0", "\0\0\0\0\0\0\0\0")]
    public void IsoDateFromYyyymmdd_ConvertsDigitsOnly(string input, string expected) =>
        Assert.Equal(expected, Db2Text.IsoDateFromYyyymmdd(input));

    [Fact]
    public async Task StoreFailure_Returns503()
    {
        var store = new Mock<IArchiveEventStore>();
        store.Setup(s => s.GetEventsAsync(It.IsAny<string>(), It.IsAny<CancellationToken>()))
            .ThrowsAsync(new ArchiveStoreUnavailableException("db2 archive query failed: SQLSTATE 08001"));
        var result = await ArchiveController.GetEvents("DOC1", Registry(Db2Options(), store.Object), default);
        Assert.Equal(StatusCodes.Status503ServiceUnavailable, ((IStatusCodeHttpResult)result).StatusCode);
    }

    [Fact]
    public async Task ArchiveHealth_OffIsDisabled_UnreachableIs503()
    {
        var off = await ArchiveController.ArchiveHealth(Registry(new ArchiveStoreOptions()), default);
        Assert.Equal(StatusCodes.Status200OK, ((IStatusCodeHttpResult)off).StatusCode);

        var store = new Mock<IArchiveEventStore>();
        store.Setup(s => s.PingAsync(It.IsAny<CancellationToken>()))
            .ThrowsAsync(new ArchiveStoreUnavailableException("down"));
        var down = await ArchiveController.ArchiveHealth(Registry(Db2Options(), store.Object), default);
        Assert.Equal(StatusCodes.Status503ServiceUnavailable, ((IStatusCodeHttpResult)down).StatusCode);
    }

    [Fact]
    public void Sql_NeverTrimsCharColumnsInSelectList()
    {
        Assert.DoesNotContain("RTRIM(F.", Db2ArchiveEventStore.Sql);
        Assert.DoesNotContain("RTRIM(F.", AzureSqlArchiveEventStore.Sql);
        Assert.DoesNotContain("RTRIM(F.", PostgresArchiveEventStore.Sql);
        Assert.Contains("ORDER BY F.EVENT_TS", Db2ArchiveEventStore.Sql);
        Assert.Contains("EVENT_TS_NANOS_TAIL", AzureSqlArchiveEventStore.Sql);
        Assert.Contains("\"EVENT_TS_NANOS_TAIL\"", PostgresArchiveEventStore.Sql);
        Assert.Equal("postgresql", new PostgresArchiveEventStore("Host=x").StoreName);
    }
}
