import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X } from 'lucide-react';
import { toast } from 'sonner';
import { usePipeline } from '../context/PipelineContext';
import type { Agency } from '../types/agency';


interface AddBusinessModalProps {
  isOpen: boolean;
  onClose: () => void;
}

const AddBusinessModal: React.FC<AddBusinessModalProps> = ({
  isOpen,
  onClose,
}) => {
  const { addToPipeline } = usePipeline();
  const [formData, setFormData] = useState({
    name: '',
    city: '',
    address: '',
    phone: '',
    website: '',
    website_status: 'NO WEBSITE',
  });

  const statusOptions = [
    'NO WEBSITE',
    'BROKEN WEBSITE',
    'INSECURE',
    'NOT MOBILE',
    'WEBSITE OK',
    'UNKNOWN',
  ];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name || !formData.city) {
      toast.error('Please fill in at least name and city');
      return;
    }

    const newAgency: Agency = {
      id: `manual-${Date.now()}`,
      name: formData.name,
      city: formData.city,
      address: formData.address,
      phone: formData.phone || undefined,
      website: formData.website || undefined,
      website_status: formData.website_status,
      discovery_method: 'Manual Entry',
    };

    try {
      await addToPipeline(newAgency);
      toast.success(`${formData.name} added to pipeline`);
      setFormData({
        name: '',
        city: '',
        address: '',
        phone: '',
        website: '',
        website_status: 'NO WEBSITE',
      });
      onClose();
    } catch {
      toast.error('Failed to add lead');
    }
  };

  const inputClass =
    'w-full h-control rounded border border-line-strong bg-canvas px-3 text-sm text-fg transition-colors';
  const labelClass = 'mb-1.5 block text-2xs font-medium text-fg-muted';

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 z-50 bg-backdrop/70"
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-labelledby="add-business-title"
            initial={{ opacity: 0, scale: 0.98, y: 8 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.98, y: 8 }}
            className="fixed inset-4 z-50 m-auto w-full max-w-md max-h-[calc(100vh-2rem)] overflow-y-auto rounded-lg border border-line-strong bg-surface shadow-overlay"
            style={{ height: 'fit-content' }}
          >
            <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
              <h2 id="add-business-title" className="text-base font-semibold text-fg">
                Add business manually
              </h2>
              <button
                onClick={onClose}
                aria-label="Close"
                className="grid size-control-sm place-content-center rounded text-fg-subtle hover:bg-raised hover:text-fg transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-3.5 p-5">
              <div>
                <label htmlFor="add-name" className={labelClass}>
                  Business name *
                </label>
                <input
                  id="add-name"
                  type="text"
                  value={formData.name}
                  onChange={(e) =>
                    setFormData({ ...formData, name: e.target.value })
                  }
                  className={inputClass}
                  required
                />
              </div>

              <div>
                <label htmlFor="add-city" className={labelClass}>
                  City *
                </label>
                <input
                  id="add-city"
                  type="text"
                  value={formData.city}
                  onChange={(e) =>
                    setFormData({ ...formData, city: e.target.value })
                  }
                  className={inputClass}
                  required
                />
              </div>

              <div>
                <label htmlFor="add-address" className={labelClass}>
                  Address
                </label>
                <input
                  id="add-address"
                  type="text"
                  value={formData.address}
                  onChange={(e) =>
                    setFormData({ ...formData, address: e.target.value })
                  }
                  className={inputClass}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="add-phone" className={labelClass}>
                    Phone
                  </label>
                  <input
                    id="add-phone"
                    type="tel"
                    value={formData.phone}
                    onChange={(e) =>
                      setFormData({ ...formData, phone: e.target.value })
                    }
                    className={inputClass}
                  />
                </div>

                <div>
                  <label htmlFor="add-status" className={labelClass}>
                    Website status
                  </label>
                  <select
                    id="add-status"
                    value={formData.website_status}
                    onChange={(e) =>
                      setFormData({ ...formData, website_status: e.target.value })
                    }
                    className={inputClass}
                  >
                    {statusOptions.map((status) => (
                      <option key={status} value={status}>
                        {status}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label htmlFor="add-website" className={labelClass}>
                  Website
                </label>
                <input
                  id="add-website"
                  type="url"
                  value={formData.website}
                  onChange={(e) =>
                    setFormData({ ...formData, website: e.target.value })
                  }
                  placeholder="www.example.com"
                  className={inputClass}
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={onClose}
                  className="h-control rounded border border-line-strong px-3.5 text-sm font-medium text-fg transition-colors hover:bg-raised"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="h-control rounded bg-accent px-3.5 text-sm font-medium text-accent-fg transition-colors hover:bg-accent-hover"
                >
                  Add to pipeline
                </button>
              </div>
            </form>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
};

export default AddBusinessModal;
