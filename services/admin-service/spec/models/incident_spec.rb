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
    it { is_expected.to validate_inclusion_of(:affected_service).in_array(described_class::AFFECTED_SERVICES).allow_blank }
  end

  describe 'scopes' do
    let!(:open_incident) { create(:incident, severity: 'high') }
    let!(:investigating) { create(:incident, :investigating, severity: 'low') }
    let!(:resolved) { create(:incident, :resolved, severity: 'high') }
    let!(:closed) { create(:incident, :closed) }

    it '.active returns open and investigating incidents' do
      expect(described_class.active).to contain_exactly(open_incident, investigating)
    end

    it '.by_status filters by status' do
      expect(described_class.by_status('resolved')).to contain_exactly(resolved)
    end

    it '.by_severity filters by severity' do
      expect(described_class.by_severity('high')).to contain_exactly(open_incident, resolved)
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

    it 'raises on an invalid transition' do
      incident = create(:incident, :resolved)
      expect { incident.investigate! }.to raise_error(described_class::InvalidTransitionError)
      expect(incident.reload.status).to eq('resolved')
    end
  end

  describe '#resolve!' do
    it 'sets status and resolved_at' do
      incident = create(:incident, :investigating)
      incident.resolve!
      incident.reload
      expect(incident.status).to eq('resolved')
      expect(incident.resolved_at).to be_present
    end

    it 'raises when already closed' do
      incident = create(:incident, :closed)
      expect { incident.resolve! }.to raise_error(described_class::InvalidTransitionError)
    end
  end

  describe '#close!' do
    it 'sets status and closed_at from resolved' do
      incident = create(:incident, :resolved)
      incident.close!
      incident.reload
      expect(incident.status).to eq('closed')
      expect(incident.closed_at).to be_present
    end

    it 'raises when the incident is still open' do
      incident = create(:incident)
      expect { incident.close! }.to raise_error(described_class::InvalidTransitionError)
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
      expect(incident).not_to have_devin_session
      expect(incident).not_to have_active_devin_session
    end

    it 'reports an active session when running' do
      incident = build(:incident, :with_devin_session)
      expect(incident).to have_devin_session
      expect(incident).to have_active_devin_session
    end

    it 'reports an inactive session when not running' do
      incident = build(:incident, :with_devin_session, devin_session_status: 'finished')
      expect(incident).to have_devin_session
      expect(incident).not_to have_active_devin_session
    end
  end
end
