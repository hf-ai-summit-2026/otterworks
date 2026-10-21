class Incident < ApplicationRecord
  SEVERITIES = %w[low medium high critical].freeze
  STATUSES = %w[open investigating resolved closed].freeze
  ACTIVE_STATUSES = %w[open investigating].freeze
  AFFECTED_SERVICES = %w[
    api-gateway auth-service file-service document-service
    collab-service notification-service search-service
    analytics-service admin-service audit-service report-service
  ].freeze

  VALID_TRANSITIONS = {
    'open'          => %w[investigating resolved],
    'investigating' => %w[resolved],
    'resolved'      => %w[closed],
    'closed'        => %w[]
  }.freeze

  validates :title, presence: true, length: { maximum: 255 }
  validates :description, presence: true
  validates :severity, presence: true, inclusion: { in: SEVERITIES }
  validates :status, presence: true, inclusion: { in: STATUSES }
  validates :affected_service, inclusion: { in: AFFECTED_SERVICES }, allow_blank: true

  scope :by_status, ->(status) { where(status: status) }
  scope :by_severity, ->(severity) { where(severity: severity) }
  scope :active, -> { where(status: ACTIVE_STATUSES) }

  # Creates an incident unless one is already active for the same service.
  # Returns [incident, created]. Atomic under concurrency: the partial unique
  # index index_incidents_on_active_affected_service rejects a second active row,
  # and the losing writer returns the winner's incident.
  def self.create_unless_active!(attrs)
    service = attrs.fetch(:affected_service)
    existing = active.find_by(affected_service: service)
    return [existing, false] if existing

    [transaction(requires_new: true) { create!(attrs) }, true]
  rescue ActiveRecord::RecordNotUnique
    [active.find_by!(affected_service: service), false]
  end

  def investigate!
    transition_to!('investigating')
  end

  def resolve!
    transition_to!('resolved', resolved_at: Time.current)
  end

  def close!
    transition_to!('closed', closed_at: Time.current)
  end

  def can_transition_to?(new_status)
    VALID_TRANSITIONS.fetch(status, []).include?(new_status)
  end

  def active?
    ACTIVE_STATUSES.include?(status)
  end

  def has_devin_session?
    devin_session_id.present?
  end

  def has_active_devin_session?
    devin_session_id.present? && devin_session_status == 'running'
  end

  private

  def transition_to!(new_status, extras = {})
    unless can_transition_to?(new_status)
      raise InvalidTransitionError, "Cannot transition from '#{status}' to '#{new_status}'"
    end

    update!(extras.merge(status: new_status))
  end

  class InvalidTransitionError < StandardError; end
end
