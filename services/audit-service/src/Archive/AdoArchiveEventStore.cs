using System.Data;
using System.Data.Common;
using System.Globalization;

namespace OtterWorks.AuditService.Archive;

/// <summary>
/// Provider-neutral assembly of the FILEAUD read: subclasses supply the connection, the SQL
/// (never trimming CHAR columns in SQL) and the row mapping.
/// </summary>
public abstract class AdoArchiveEventStore : IArchiveEventStore
{
    public abstract string StoreName { get; }

    protected abstract DbConnection CreateConnection();

    protected abstract string EventsSql { get; }

    protected abstract string PingSql { get; }

    protected abstract string VersionsSql { get; }

    protected abstract ArchiveEventRow MapRow(DbDataReader reader);

    protected abstract ArchiveVersionRow MapVersion(DbDataReader reader);

    public async Task<IReadOnlyList<ArchiveEventRow>?> GetEventsAsync(string docId, CancellationToken cancellationToken)
    {
        try
        {
            await using var connection = CreateConnection();
            await connection.OpenAsync(cancellationToken);
            await using var command = CreateDocCommand(connection, EventsSql, docId);

            var rows = new List<ArchiveEventRow>();
            var anyVersion = false;
            await using var reader = await command.ExecuteReaderAsync(cancellationToken);
            while (await reader.ReadAsync(cancellationToken))
            {
                anyVersion = true;
                if (await reader.IsDBNullAsync("AUDIT_KEY", cancellationToken))
                {
                    continue;
                }

                rows.Add(MapRow(reader));
            }

            return anyVersion ? rows : null;
        }
        catch (DbException ex)
        {
            throw new ArchiveStoreUnavailableException($"{StoreName} archive query failed: {ex.Message}", ex);
        }
    }

    public async Task<IReadOnlyList<ArchiveVersionRow>?> GetDocumentAsync(string docId, CancellationToken cancellationToken)
    {
        var versions = new List<ArchiveVersionRow>();
        try
        {
            await using var connection = CreateConnection();
            await connection.OpenAsync(cancellationToken);
            await using (var command = CreateDocCommand(connection, VersionsSql, docId))
            await using (var reader = await command.ExecuteReaderAsync(cancellationToken))
            {
                while (await reader.ReadAsync(cancellationToken))
                {
                    versions.Add(MapVersion(reader));
                }
            }

            if (versions.Count == 0)
            {
                return null;
            }

            var byKey = versions.ToDictionary(v => v.ArchKey, v => v);
            await using (var command = CreateDocCommand(connection, EventsSql, docId))
            await using (var reader = await command.ExecuteReaderAsync(cancellationToken))
            {
                while (await reader.ReadAsync(cancellationToken))
                {
                    if (await reader.IsDBNullAsync("AUDIT_KEY", cancellationToken))
                    {
                        continue;
                    }

                    var row = MapRow(reader);
                    if (byKey.TryGetValue(row.ArchKey, out var version))
                    {
                        version.Events.Add(row);
                    }
                }
            }

            return versions;
        }
        catch (DbException ex)
        {
            throw new ArchiveStoreUnavailableException($"{StoreName} archive query failed: {ex.Message}", ex);
        }
    }

    private static DbCommand CreateDocCommand(DbConnection connection, string sql, string docId)
    {
        var command = connection.CreateCommand();
        command.CommandText = sql; // nosemgrep: csharp.lang.security.sqli.csharp-sqli.csharp-sqli -- callers pass const SQL, docId bound as @docId
        var parameter = command.CreateParameter();
        parameter.ParameterName = "@docId";
        parameter.DbType = DbType.String;
        parameter.Value = docId;
        command.Parameters.Add(parameter);
        return command;
    }

    public async Task PingAsync(CancellationToken cancellationToken)
    {
        try
        {
            await using var connection = CreateConnection();
            await connection.OpenAsync(cancellationToken);
            await using var command = connection.CreateCommand();
            command.CommandText = PingSql; // nosemgrep: csharp.lang.security.sqli.csharp-sqli.csharp-sqli -- constant SQL
            await command.ExecuteScalarAsync(cancellationToken);
        }
        catch (DbException ex)
        {
            throw new ArchiveStoreUnavailableException($"{StoreName} archive store unreachable: {ex.Message}", ex);
        }
    }

    protected static byte[] Bytes(DbDataReader reader, string column)
    {
        var ordinal = reader.GetOrdinal(column);
        if (reader.IsDBNull(ordinal))
        {
            return Array.Empty<byte>();
        }

        var length = (int)reader.GetBytes(ordinal, 0, null, 0, 0);
        var buffer = new byte[length];
        reader.GetBytes(ordinal, 0, buffer, 0, length);
        return buffer;
    }

    protected static string Str(DbDataReader reader, string column) =>
        reader.IsDBNull(reader.GetOrdinal(column)) ? string.Empty : reader.GetString(reader.GetOrdinal(column));

    // SMALLINT columns (VERSION_NO) surface as Int16 from both providers; GetInt32 throws on them.
    protected static int Int(DbDataReader reader, string column) =>
        Convert.ToInt32(reader.GetValue(reader.GetOrdinal(column)), CultureInfo.InvariantCulture);
}
