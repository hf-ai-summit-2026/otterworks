require 'rails_helper'

RSpec.describe Incident do
  describe 'validations' do
    it { is_expected.to validate_presence_of(:title) }
    it { is_expected.to validate_length_of(:title).is_at_most(255) }
    it { is_expected.to validate_presence_of(:description) }
    it { is_expected.to validate_inclusion_of(:severity).in_array(described_class::SEVERITIES) }
    it { is_expected.to validate_inclusion_of(:status).in_array(described_class::STATUSES) }

    it 'allows a blank affected_service' do
      expect(build(:incident, affected_service: nil)).to be_valid
    end

    it 'rejects an unknown affected_service' do
      incident = build(:incident, affected_service: 'not-a-service')
      expect(incident).not_to be_valid
      expect(incident.errors[:affected_service]).to be_present
    end
  end

  describe '.active' do
    let!(:open_incident) { create(:incident) }
    let!(:investigating) { create(:incident, :investigating) }
    let!(:resolved) { create(:incident, :resolved) }
    let!(:closed) { create(:incident, :closed) }

    it 'returns only open and investigating incidents' do
      expect(described_class.active).to contain_exactly(open_incident, investigating)
    end
  end

  describe '#can_transition_to?' do
    {
      'open' => { allowed: %w[investigating resolved], denied: %w[open closed] },
      'investigating' => { allowed: %w[resolved], denied: %w[open investigating closed] },
      'resolved' => { allowed: %w[closed], denied: %w[open investigating resolved] },
      'closed' => { allowed: [], denied: %w[open investigating resolved closed] }
    }.each do |from, rules|
      rules[:allowed].each do |to|
        it "allows #{from} -> #{to}" do
          expect(build(:incident, status: from).can_transition_to?(to)).to be(true)
        end
      end

      rules[:denied].each do |to|
        it "denies #{from} -> #{to}" do
          expect(build(:incident, status: from).can_transition_to?(to)).to be(false)
        end
      end
    end
  end

  describe '#investigate!' do
    it 'moves an open incident to investigating' do
      incident = create(:incident)
      incident.investigate!
      expect(incident.reload.status).to eq('investigating')
    end

    it 'raises when the incident is already resolved' do
      incident = create(:incident, :resolved)
      expect { incident.investigate! }.to raise_error(Incident::InvalidTransitionError)
      expect(incident.reload.status).to eq('resolved')
    end
  end

  describe '#resolve!' do
    it 'resolves an investigating incident and stamps resolved_at' do
      incident = create(:incident, :investigating)
      incident.resolve!
      expect(incident.reload.status).to eq('resolved')
      expect(incident.resolved_at).to be_within(5.seconds).of(Time.current)
    end

    it 'raises when the incident is closed' do
      incident = create(:incident, :closed)
      expect { incident.resolve! }.to raise_error(Incident::InvalidTransitionError)
    end
  end

  describe '#close!' do
    it 'closes a resolved incident and stamps closed_at' do
      incident = create(:incident, :resolved)
      incident.close!
      expect(incident.reload.status).to eq('closed')
      expect(incident.closed_at).to be_within(5.seconds).of(Time.current)
    end

    it 'raises when the incident is still open' do
      incident = create(:incident)
      expect { incident.close! }.to raise_error(Incident::InvalidTransitionError)
      expect(incident.reload.closed_at).to be_nil
    end
  end

  describe '#active?' do
    it 'is true for open and investigating incidents' do
      expect(build(:incident)).to be_active
      expect(build(:incident, :investigating)).to be_active
    end

    it 'is false for resolved and closed incidents' do
      expect(build(:incident, :resolved)).not_to be_active
      expect(build(:incident, :closed)).not_to be_active
    end
  end

  describe 'Devin session helpers' do
    it 'reports no session when devin_session_id is blank' do
      incident = build(:incident)
      expect(incident.has_devin_session?).to be(false)
      expect(incident.has_active_devin_session?).to be(false)
    end

    it 'reports an active session only while running' do
      incident = build(:incident, devin_session_id: 'devin-abc', devin_session_status: 'running')
      expect(incident.has_devin_session?).to be(true)
      expect(incident.has_active_devin_session?).to be(true)

      incident.devin_session_status = 'finished'
      expect(incident.has_active_devin_session?).to be(false)
    end
  end
end
