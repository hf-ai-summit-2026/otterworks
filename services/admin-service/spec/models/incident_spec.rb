require 'rails_helper'

RSpec.describe Incident do
  describe 'validations' do
    subject { build(:incident) }

    it { is_expected.to validate_presence_of(:title) }
    it { is_expected.to validate_length_of(:title).is_at_most(255) }
    it { is_expected.to validate_presence_of(:description) }
    it { is_expected.to validate_presence_of(:severity) }
    it { is_expected.to validate_inclusion_of(:severity).in_array(described_class::SEVERITIES) }
    it { is_expected.to validate_presence_of(:status) }
    it { is_expected.to validate_inclusion_of(:status).in_array(described_class::STATUSES) }
    it { is_expected.to validate_inclusion_of(:affected_service).in_array(described_class::AFFECTED_SERVICES) }

    it 'allows a blank affected_service' do
      expect(build(:incident, affected_service: nil)).to be_valid
    end
  end

  describe 'scopes' do
    let!(:open_incident) { create(:incident, severity: 'high') }
    let!(:investigating_incident) { create(:incident, :investigating, severity: 'low') }
    let!(:resolved_incident) { create(:incident, :resolved, severity: 'high') }

    it '.by_status filters by status' do
      expect(described_class.by_status('resolved')).to contain_exactly(resolved_incident)
    end

    it '.by_severity filters by severity' do
      expect(described_class.by_severity('high')).to contain_exactly(open_incident, resolved_incident)
    end

    it '.active returns open and investigating incidents' do
      expect(described_class.active).to contain_exactly(open_incident, investigating_incident)
    end
  end

  describe '#can_transition_to?' do
    it 'follows VALID_TRANSITIONS' do
      described_class::VALID_TRANSITIONS.each do |from, allowed|
        incident = build(:incident, status: from)
        described_class::STATUSES.each do |to|
          expect(incident.can_transition_to?(to)).to eq(allowed.include?(to)), "#{from} -> #{to}"
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

    it 'raises on an invalid transition and leaves status unchanged' do
      incident = create(:incident, :resolved)
      expect { incident.investigate! }.to raise_error(Incident::InvalidTransitionError, /resolved.*investigating/)
      expect(incident.reload.status).to eq('resolved')
    end
  end

  describe '#resolve!' do
    it 'moves an investigating incident to resolved and stamps resolved_at' do
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
    it 'moves a resolved incident to closed and stamps closed_at' do
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
      incident = build(:incident, devin_session_id: nil)
      expect(incident.has_devin_session?).to be(false)
      expect(incident.has_active_devin_session?).to be(false)
    end

    it 'reports an active session only when status is running' do
      running = build(:incident, devin_session_id: 'sess-1', devin_session_status: 'running')
      finished = build(:incident, devin_session_id: 'sess-2', devin_session_status: 'finished')

      expect(running.has_active_devin_session?).to be(true)
      expect(finished.has_devin_session?).to be(true)
      expect(finished.has_active_devin_session?).to be(false)
    end
  end
end
