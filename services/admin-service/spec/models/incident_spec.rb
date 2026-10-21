require 'rails_helper'

RSpec.describe Incident do
  let(:attrs) do
    {
      title: 'search-service alert firing',
      description: 'High error rate',
      severity: 'high',
      status: 'open',
      affected_service: 'search-service'
    }
  end

  describe 'active incident uniqueness' do
    it 'rejects a second active incident for the same service at the database level' do
      create(:incident, status: 'investigating')

      expect { described_class.new(attrs).save!(validate: false) }
        .to raise_error(ActiveRecord::RecordNotUnique)
    end

    it 'allows a new active incident once the previous one is resolved' do
      create(:incident).resolve!

      expect { create(:incident) }.not_to raise_error
    end

    it 'allows concurrent active incidents for different services' do
      create(:incident, affected_service: 'search-service')

      expect { create(:incident, affected_service: 'file-service') }.not_to raise_error
    end
  end

  describe '.create_unless_active!' do
    it 'creates an incident when none is active for the service' do
      incident, created = described_class.create_unless_active!(attrs)

      expect(created).to be(true)
      expect(incident).to be_persisted
    end

    it 'returns the existing active incident instead of creating another' do
      existing = create(:incident)

      incident, created = described_class.create_unless_active!(attrs)

      expect(created).to be(false)
      expect(incident).to eq(existing)
      expect(described_class.count).to eq(1)
    end

    it 'returns the winning incident when a concurrent writer inserts first' do
      winner = create(:incident)
      # Simulate losing the race: the pre-check misses the winner's row.
      allow(described_class).to receive(:active)
        .and_return(described_class.none, described_class.where(status: described_class::ACTIVE_STATUSES))

      incident, created = described_class.create_unless_active!(attrs)

      expect(created).to be(false)
      expect(incident).to eq(winner)
      expect(described_class.where(affected_service: 'search-service').count).to eq(1)
    end
  end
end
