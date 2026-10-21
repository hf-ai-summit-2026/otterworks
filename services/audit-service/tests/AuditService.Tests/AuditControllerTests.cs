using OtterWorks.AuditService.Controllers;

namespace AuditService.Tests;

public class AuditControllerTests
{
    [Theory]
    [InlineData(null, null, 1, 20)]
    [InlineData(3, 50, 3, 50)]
    [InlineData(0, 20, 1, 20)]
    [InlineData(-5, 20, 1, 20)]
    [InlineData(int.MinValue, 20, 1, 20)]
    [InlineData(1, 0, 1, 1)]
    [InlineData(1, -10, 1, 1)]
    [InlineData(1, 1000, 1, 100)]
    public void NormalizePaging_ClampsPageAndSize(int? page, int? size, int expectedPage, int expectedSize)
    {
        var (actualPage, actualSize) = AuditController.NormalizePaging(page, size);

        Assert.Equal(expectedPage, actualPage);
        Assert.Equal(expectedSize, actualSize);
    }
}
